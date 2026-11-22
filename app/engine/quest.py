from dataclasses import dataclass
from typing import List, Dict, Tuple, Set

from app.data.database.database import DB

from app.utilities import utils, static_random
from app.utilities.typing import NID

"""
RAW DATA SCHEMA

quests:             list(nid, negator, location, weight, point)
penalties:          dict
artifacts:          dict
reward_locations:   list(nid)
init_quests:        list(nid, goal, done, limit, reward)
init_attempts:      list(nid)
init_penalty:       str
pref_quest:         float
pref_artifact:      float
min_quest:          int
max_quest:          int
penalty_limit:      int
"""

def d(nid: str):
    return DB.raw_data.get(nid)

@dataclass
class Quest():
    nid: NID
    goal: str
    done: bool
    limit: int
    reward: str

    def get_blurb(self) -> str:
        return '%s of <blue>%s</>.||<yellow>Participation Count:</> %d.||<yellow>Reward:</> %s.' \
                % (self.goal, self.nid, self.limit, self.reward.replace('_', ' '))

    def save(self):
        s_dict = {
            'nid':      self.nid,
            'goal':     self.goal,
            'done':     self.done,
            'limit':    self.limit,
            'reward':   self.reward
        }
        return s_dict

    @classmethod
    def restore(cls, s_dict):
        return cls(*s_dict.values())

    @classmethod
    def restore_from_rawdata(cls, obj):
        return cls(obj.nid, obj.goal, obj.done == 'True', int(obj.limit), obj.reward)


class QuestManager():
    def __init__(self, seed=0):
        self.random: static_random.LCG = static_random.get_generator(seed)

        self.avail_artifact: List[str] = list(d('artifacts').keys())
        self.avail_penalty:  List[str] = list(d('penalties').keys())
        self.avail_quest:    List[str] = [quest.nid for quest in d('quests') if quest.nid not in self.avail_penalty]

        self.quests:     Dict[NID, Quest] = {quest.nid : Quest.restore_from_rawdata(quest) for quest in d('init_quests')}
        self.attempt:    List[NID] = [attempt.nid for attempt in d('init_attempts')]
        self.penalty:    str = d('init_penalty')
        self.current:    NID = None

        self.rewards:    List[str] = []
        self.artifacts:  Dict[str, List[str]] = {}

        self.point:         int = 0
        self.penalty_count: int = 0

    def norm(self, weight: str):
        return 100 - abs(int(weight) - self.point)

    def draw_lot(self, options: dict):
        res = list(options.keys())[static_random.weighted_choice(options.values(), self.random)]
        options.pop(res)
        return res

    def generate_quests(self, seat_count: int, member_count: int):       
        quest_list = []
        quest_count = self.random.randint(int(d('min_quest')), int(d('max_quest')))
        if len(self.avail_quest) < quest_count:
            quest_list = self.avail_quest
            self.avail_quest = []
        else:
            quest_options = {i : self.norm(d('quests').get(i).weight) for i in self.avail_quest}
            for i in range(quest_count):
                task = self.draw_lot(quest_options)
                self.avail_quest.remove(task)
                quest_list.append(task)
        
        potential_member_count = member_count + sum(task[:2] == 'Un' for task in quest_list)
        potential_seat_count = seat_count 

        reward_options = {}
        for i in self.avail_quest:
            reward_options['Location of %s' % i] = int(self.norm(d('quests').get(i).weight) * float(d('pref_quest')))
        for i in self.avail_artifact:
            reward_options['Location of Artifact %s' % i] = int(self.norm(d('artifacts')[i]) * float(d('pref_artifact')))

        for idx, nid in enumerate(quest_list):
            if reward_options:
                if potential_seat_count < 12:
                    mean = sum(reward_options.values()) / len(reward_options.values())
                    seat_rate = mean * (2 ** (potential_member_count - potential_seat_count))
                    reward_options['Addition of a Roundtable Seat'] = int(seat_rate)
                reward = self.draw_lot(reward_options)
                if reward == 'Addition of a Roundtable Seat':
                    potential_seat_count += 1
            elif potential_seat_count < 12:
                reward = 'Addition of a Roundtable Seat'
                potential_seat_count += 1
            else:
                reward = '10,000g'

            # goal = 'Capture' if nid[0:2] == 'Un' or self.random.randint(0, 1) else 'Neutralisation'
            goal = 'Capture' if nid[0:2] == 'Un' else 'Neutralisation'
            limit = (self.random.randint(1, seat_count) + self.random.randint(1, seat_count) + 1) // 2

            self.quests[nid] = Quest(nid, goal, False, limit, reward)

        if self.penalty_count == int(d('penalty_limit')):
            self.penalty = 'Ragnarok'
        else:
            penalty_options = {i: self.norm(d('penalties')[i]) for i in self.avail_penalty}
            self.penalty = self.draw_lot(penalty_options)
            self.avail_penalty.remove(self.penalty)

    def start_quest_phase(self):
        from app.engine.game_state import game

        self.avail_quest += self.rewards
        self.avail_artifact += utils.flatten_list(self.artifacts.values())
        self.rewards = []
        self.artifacts = {}
        self.generate_quests(game.game_vars.get('roundtable_seat'), len(game.get_player_units(False)))

    def end_quest_phase(self) -> Tuple[str, str, str]:
        if all(quest.done for quest in self.quests.values()):
            msg = 'All quests have been cleared. Use your rewards wisely, you gonna need them.'
            sty = None
            res = 'success'

        elif self.penalty == 'Ragnarok':
            msg = "Ha!|HAHAHA!|It's starting, the final war|<jitter>Ragnarok</>!"
            sty = 'noir'
            res = 'ragnarok'

        else:
            msg = "You shall receive the penalty. Now adding...|UMA %s!" % self.penalty
            sty = 'noir'
            res = 'penalty'

            if self.penalty in d('quests'):
                self.avail_quest.append(self.penalty)
            self.penalty_count += 1

        self.quests = {}
        self.attempt = []
        self.penalty = None

        return msg, sty, res

    def quest_result(self, quest: Quest) -> Tuple[str, str, str]:
        from app.engine.game_state import game

        point = 0
        if d('quests').get(quest.nid):
            point = d('quests').get(quest.nid).point
        self.point += point

        if not quest.done:
            '''
            if not (quest.nid[0:2] == 'Un' and game.check_dead(d('quests').get(quest.nid).negator)):
                self.avail_quest.append(quest.nid)
            '''
            self.point -= point

            pos = ()
            msg = '<red>Fail!</>'
            res = 'fail'

        elif quest.reward == 'Addition of a Roundtable Seat':
            roundtable_seat = game.game_vars.get('roundtable_seat')
            pos_roundtable = game.game_vars.get('pos_roundtable')
            pos_apoccy = game.game_vars.get('pos_apoccy')

            offset = map(lambda x: min(x-1, 2) if x > 0 else max(x+1, -2) if x < 0 else x, pos_roundtable[roundtable_seat])
            pos = utils.tuple_add(pos_apoccy, tuple(offset))
            
            suffix = 'rd' if roundtable_seat == 2 else 'th'
            msg = "<blue>Success!</>|Adding the %d%s Seat." % (roundtable_seat + 1, suffix)

            res = 'seat'

        elif quest.reward == '10,000g':
            pos = ()
            msg = "<blue>Success!</>|Giving 10,000 golds."
            res = 'money'

        else:
            name = quest.reward[12::]
            if name[0:8] == 'Artifact':
                location = self.random.choice(d('reward_locations')).nid
                if self.artifacts.get(location):
                    self.artifacts[location].append(name[9::])
                else:
                    self.artifacts[location] = [name[9::]]

            else:
                location = d('quests').get(name).location
                self.rewards.append(name)

                if name[0:2] != 'Un':
                    name = 'UMA %s' % name

            pos = DB.levels.get('Overworld').regions.get(location).position
            msg = "<blue>Success!</>|Marking %s." % name
            res = 'location'

        return str(pos), "%s of %s,|%s" % (quest.goal, quest.nid, msg), res

    def get_quest_info(self, idx: int) -> str:
        if idx:
            return list(self.quests.values())[idx-1].get_blurb()
        elif self.penalty == 'Ragnarok':
            suffix = 'the final war <jitter><blue>Ragnarok</>.'
        else:
            warning = 'Accumulating %s penalties will trigger <jitter><blue>Ragnarok</>.' % d('penalty_limit')
            suffix = 'penalty: Addition of UMA <blue>%s</>.||%s' % (self.penalty, warning)
        return '<red>Warning:</>|Passing will incur %s' % suffix

    def get_quest_choice(self) -> Tuple[str, str]:
        title = "<yellow>Penalty %d: %s</>" % (self.penalty_count + 1, self.penalty)

        options = ','.join(['%d|Quest %d' % (i+1, i+1) for i in range(len(self.quests))]) + ',0|<green>Pass</>'

        return title, options

    def is_quest_phase(self) -> bool:
        return bool(self.quests)

    def is_done(self) -> bool:
        return len(self.attempt) >= len(self.quests)

    def get_location(self) -> Set[str]:
        return set(d('quests').get(nid).location for nid, quest in self.quests.items() if not quest.done)

    def get_pin(self) -> Set[str]:
        return set([d('quests').get(reward).location for reward in self.rewards] + list(self.artifacts.keys()))

    def get_options_from_location(self, location: str) -> List[str]:
        if self.is_quest_phase():
            options = ['%s|%s of %s' % (nid, quest.goal, nid)
                        for nid, quest in self.quests.items()
                        if not quest.done and d('quests').get(nid).location == location]
        else:
            options = ['%s|Locating %s' % (reward, reward)
                        for reward in self.rewards
                        if d('quests').get(nid).location == location] + \
                      ['%s|Locating Artifacts' % location] if self.artifacts.get(location) else []

        if len(options) == 1:
            self.current = options[0].split('|')[0]
            return []

        return ','.join(options)

    def set_current(self, nid: str):
        self.current = nid

    def unit_death(self, unit):
        # if UMA
        #   if quest
        #       mark quest done
        #       check goal
        #   else 
        #       remove avail quest
        #       choose goal
        #
        #   if capture
        #       resurrect unit
        #       add to party
        #   
        # elif quest
        #       mark quest fail
        #
        # elif not recruited
        #       remove avail quest

        pass

    def unit_recruit(self, unit):
        # if quest
        #       mark quest done
        #       add to party
        #
        # else
        #       remove avail quest

        pass

    def artifact_pickup(self, artifact: str):
        self.avail_artifact.remove(artifact)

    def end_chapter(self):
        if self.is_quest_phase():
            self.attempt.append(self.current)
        elif not self.artifacts.get(self.current):
            self.rewards.remove(self.current)
        else:
            self.artifacts.remove(self.current)

        self.current = None

    def cheat(self):
        for quest in self.quests.values():
            quest.done = True

    def save(self):
        s_dict = {
            'random':           self.random.serialize(),
            'avail_quest':      self.avail_quest,
            'avail_penalty':    self.avail_penalty,
            'avail_artifact':   self.avail_artifact,

            'quests':           [quest.save() for quest in self.quests.values()],
            'current':          self.current,
            'attempt':          self.attempt,
            'penalty':          self.penalty,

            'rewards':          self.rewards,
            'artifacts':        self.artifacts,

            'point':            self.point,
            'penalty_count':    self.penalty_count
        }
        return s_dict

    @classmethod
    def restore(cls, s_dict):
        obj = cls(s_dict['random'])
        obj.avail_quest = s_dict['avail_quest']
        obj.avail_penalty = s_dict['avail_penalty']
        obj.avail_artifact = s_dict['avail_artifact']

        obj.quests = {quest['nid'] : Quest.restore(quest) for quest in s_dict['quests']}
        obj.current = s_dict['current']
        obj.attempt = s_dict['attempt']
        obj.penalty = s_dict['penalty']

        obj.rewards = s_dict['rewards']
        obj.artifacts = s_dict['artifacts']

        obj.point = s_dict['point']
        obj.penalty_count = s_dict['penalty_count']

        return obj

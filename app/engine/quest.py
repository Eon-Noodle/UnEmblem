from dataclasses import dataclass
from typing import List, Dict, Tuple, Set

from app.data.database.database import DB

from app.utilities import utils, static_random
from app.utilities.typing import NID

# CONSTANTS
MIN_QUEST: int = 1
MAX_QUEST: int = 4

PREF_QUEST: float = 1
PREF_ARTIFACT: float = 1

WEIGHT_QUEST: Dict[str, int] = {
    'Untruth':      4,
    'Unchange':     4,
    'Unseen':       3,
    'Unmove':       2,
    'Unfeel':       1,

    'Wolf':         2,
    'Seafoam':      2,
    'Colour':       2
}
WEIGHT_PENALTY: Dict[str, int] = {
    'Galaxy':       1,
    'Fog':          1
}
WEIGHT_ARTIFACT: Dict[str, int] = {
    'Soul_Caliber':     1,
    'Game_of_Death':    1
}

LOCATION_LIST: List[str] = [
    'Uk',
    'France',
    'Romania',
    'Moscow',
    'Turkey',
    'Siberia',
    'Japan',
    'Taiwan',
    'HongKong',
    'Buroja',
    'Aus',
    'Vancouver',
    'Vegas',
    'Nyc',
    'Rio'
]
LOCATION_DICT: Dict[str, str] = {
    'Untruth':      'HongKong',
    'Unchange':     'Siberia',
    'Unseen':       'Rio',
    'Unmove':       'Rio',

    'Wolf':         'Buroja',
    'Seafoam':      'Siberia',
    'Colour':       'Romania'
}

NEGATOR_DICT: Dict[str, str] = {
    'Untruth':      'Shen',
    'Unchange':     'Gina',
    'Unseen':       'Sean',
    'Unmove':       'Chikara',
    'Unfeel':       'Phil'
}


@dataclass
class Quest():
    """
    Class representing a quest task
    """
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


class QuestManager():
    def __init__(self, seed=0):
        self.random: static_random.LCG = static_random.get_generator(seed)

        self.avail_quest:    List[str] = list(WEIGHT_QUEST.keys())
        self.avail_penalty:  List[str] = list(WEIGHT_PENALTY.keys())
        self.avail_artifact: List[str] = list(WEIGHT_ARTIFACT.keys())

        self.quests:     Dict[NID, Quest] = {}
        self.attempt:    List[NID] = []
        self.penalty:    str = ''
        self.current:    NID = None

        self.rewards:    List[str] = []
        self.artifacts:  Dict[str, List[str]] = {}

        self.quests = {
            'Gunpowder': Quest('Gunpowder', 'Neutralization', True, 2, 'Addition of a Roundtable Seat'),
            'Untruth': Quest('Untruth', 'Capture', True, 2, 'Addition of a Roundtable Seat')
        }
        self.attempt = ['Gunpowder', 'Untruth']

    def draw_lot(self, options: dict):
        res = list(options.keys())[static_random.weighted_choice(options.values(), self.random)]
        options.pop(res)
        return res

    def generate_quests(self, seat_count: int, member_count: int):       
        quest_list = []
        quest_count = self.random.randint(MIN_QUEST, MAX_QUEST)
        if len(self.avail_quest) < quest_count:
            quest_list = self.avail_quest
        else:
            quest_options = {i : WEIGHT_QUEST.get(i) for i in self.avail_quest}
            for i in range(quest_count):
                task = self.draw_lot(quest_options)
                self.avail_quest.remove(task)
                quest_list.append(task)
        
        potential_member_count = member_count + sum(task[:2] == 'Un' for task in quest_list)
        potential_seat_count = seat_count 

        reward_options = {}
        for i in self.avail_quest:
            reward_options['Location of %s' % i] = int(WEIGHT_QUEST.get(i) * PREF_QUEST)
        for i in self.avail_artifact:
            reward_options['Location of Artifact %s' % i] = int(WEIGHT_ARTIFACT.get(i) * PREF_ARTIFACT)

        for idx, nid in enumerate(quest_list):
            mean = sum(reward_options.values()) / len(reward_options.values())
            seat_rate = mean * (2 ** (potential_member_count - potential_seat_count))
            reward_options['10,000g'] = int(mean)
            reward_options['Addition of a Roundtable Seat'] = int(seat_rate)

            goal = 'Capture' if nid[0:2] == 'Un' or self.random.randint(0, 1) else 'Neutralization'
            limit = (self.random.randint(1, seat_count) + self.random.randint(1, seat_count) + 1) // 2
            reward = self.draw_lot(reward_options)
            if reward == 'Addition of a Roundtable Seat':
                potential_seat_count += 1

            self.quests[nid] = Quest(nid, goal, False, limit, reward)

        penalty_options = {i: WEIGHT_PENALTY.get(i) for i in self.avail_penalty}
        self.penalty = self.draw_lot(penalty_options)

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
            msg = "Ha!|HAHAHA!|It's starting, the final war|<orange>Ragnarok!</>"
            sty = 'noir'
            res = 'ragnarok'

        else:
            msg = "You shall receive the penalty. Now adding...|<orange>UMA %s!</>" % self.penalty
            sty = 'noir'
            res = 'penalty'

            self.avail_quest.append(self.penalty)
            self.avail_penalty.remove(self.penalty)

        self.quests = {}
        self.attempt = []
        self.penalty = None

        return msg, sty, res

    def quest_result(self, quest: Quest) -> Tuple[str, str, str]:
        from app.engine.game_state import game

        if not quest.done:
            if not (quest.nid[0:2] == 'Un' and game.check_dead(NEGATOR_DICT[quest.nid])):
                self.avail_quest.append(quest)
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
                location = self.random.choice(LOCATION_LIST)
                if self.artifacts.get(location):
                    self.artifacts[location].append(name[9::])
                else:
                    self.artifacts[location] = [name[9::]]

            else:
                location = LOCATION_DICT.get(name)
                self.rewards.append(name)

                if name[0:2] != 'Un':
                    name = 'UMA %s' % name

            pos = DB.levels.get('Overworld').regions.get(location).position
            msg = "<blue>Success!</>|Marking %s on the map." % name
            res = 'location'

        return str(pos), "%s of %s,|%s" % (quest.goal, quest.nid, msg), res

    def get_quest_info(self, idx: int) -> str:
        if idx:
            return list(self.quests.values())[idx-1].get_blurb()
        elif self.penalty == 'Ragnarok':
            suffix = 'the final war <jitter><blue>Ragnarok</>.'
        else:
            warning = 'Accumulating 30 penalties will trigger <jitter><blue>Ragnarok</>.'
            suffix = 'penalty: Addition of UMA <blue>%s</>.||%s' % (self.penalty, warning)
        return '<red>Warning:</>|Passing will incur %s' % suffix

    def get_quest_choice(self) -> Tuple[str, str]:
        penalty_count = len(WEIGHT_PENALTY) - len(self.avail_penalty) + 1
        title = "<yellow>Penalty %d: %s</>" % (penalty_count, self.penalty)

        options = ','.join(['%d|Quest %d' % (i+1, i+1) for i in range(len(self.quests))]) + ',0|<green>Pass</>'

        return title, options

    def is_quest_phase(self) -> bool:
        return bool(self.quests)

    def is_done(self) -> bool:
        return len(self.attempt) >= len(self.quests)

    def get_location(self) -> Set[str]:
        return set(LOCATION_DICT.get(nid) for nid, quest in self.quests.items() if not quest.done)

    def get_pin(self) -> Set[str]:
        return set([LOCATION_DICT.get(reward) for reward in self.rewards] + list(self.artifacts.keys()))

    def get_options_from_location(self, location: str) -> List[str]:
        if self.is_quest_phase():
            options = ['%s|%s of %s' % (nid, quest.goal, nid) for nid, quest in self.quests.items() if not quest.done and LOCATION_DICT.get(nid) == location]
        else:
            options = ['%s|Locating %s' % (reward, reward) for reward in self.rewards if LOCATION_DICT.get(nid) == location] + \
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
            'artifacts':        self.artifacts
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

        return obj


# Testing
# Run "python -m app.engine.quest" from main directory
if __name__ == '__main__':
    import re
    import random
    import json

    q = QuestManager(random.randint(0, 100))
    q.generate_quests(2, 8)

    for quest in q.quests.values():
        blurb = q.get_quest_info(quest)
        st = re.sub('<.*?>', '', blurb)
        for line in st.split('||'):
            print(line)
        print()
    print('Penalty: %s' % q.penalty, end='\n\n')
    print(json.dumps(q.save(), indent=4))

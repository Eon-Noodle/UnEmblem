import random

from app.engine import engine
from app import counters
from app.constants import COLORKEY
from app.utilities import utils

class InfoMenuPortrait():
    def __init__(self, portrait, should_blink: bool = False, wink_instead: bool = False, blip: bool = False):
        self.portrait = portrait
        if not self.portrait.image:
            self.portrait.image = engine.image_load(self.portrait.full_path)
        self.portrait.image = self.portrait.image.convert()
        engine.set_colorkey(self.portrait.image, COLORKEY, rleaccel=True)
        self.main_portrait = engine.subsurface(self.portrait.image, self.portrait.get_face_frame())
        self.mouth_section = engine.subsurface(self.portrait.image, self.portrait.get_neutral_mouth())

        self.should_blink = should_blink
        self.blink_counter = counters.FaceBlinkCounter(portrait.blink_frames, engine.get_time())

        timer = 7000 + random.choice(range(-2000, 2000, 125))
        self.wink_instead = wink_instead
        self.wink_counter = counters.BlinkCounter(
                                portrait.blink_frames,
                                [timer, utils.frames2ms(3), timer]
                            )

        self.blip = blip
        if blip:
            self.blink_counter.update_times[-1] *= 5

    def create_image(self):
        main_image = self.main_portrait.copy()

        if self.should_blink:
            if self.wink_instead:
                left_wink_idx = self.wink_counter.get_blink_index()
                right_wink_idx = self.wink_counter.count

                if right_wink_idx:
                    left_wink = engine.subsurface(
                                    self.portrait.image,
                                    self.portrait.get_wink_frame(left_wink_idx, left_wink=True)
                                )
                    main_image.blit(left_wink, self.portrait.get_wink_coord(left_wink=True))

                if left_wink_idx:
                    right_wink = engine.subsurface(
                                    self.portrait.image,
                                    self.portrait.get_wink_frame(right_wink_idx, left_wink=False)
                                )
                    main_image.blit(right_wink, self.portrait.get_wink_coord(left_wink=False))

            elif not self.blink_counter.is_open_eyes():
                if self.blink_counter.count == self.blink_counter.max_count and self.blip:
                    return engine.empty_surf()
                blink_image = engine.subsurface(self.portrait.image,
                                    self.portrait.get_blink_frame(self.blink_counter.get_blink_index()))
                main_image.blit(blink_image, self.portrait.get_blink_coord())

        main_image.blit(self.mouth_section, self.portrait.get_mouth_coord())
        return main_image

    def update(self):
        self.blink_counter.update(engine.get_time())
        self.wink_counter.update(engine.get_time())

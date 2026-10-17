"""One presentation contract for the trial, authoring tools and exported evidence."""

WEB_BATTLE_REVISION = 'web-arena-v18-family-effects-r1'
CLASSIC_REVISION = 'device-v1'


def normalize_mode(mode='arena'):
    if mode not in ('arena', 'classic'):
        raise ValueError('mode 必须为 arena 或 classic')
    return mode


def mode_info(mode='arena'):
    mode = normalize_mode(mode)
    arena = mode == 'arena'
    revision = WEB_BATTLE_REVISION if arena else CLASSIC_REVISION
    return {'mode': mode, 'label': '竞技试玩' if arena else '经典 / 设备',
            'width': 960 if arena else 240, 'height': 640 if arena else 320,
            'presentation': revision, 'render_revision': revision,
            'revision': revision, 'ruleset': 'arena_v1' if arena else 'base_v1',
            'stat_mode': 'budget_v1' if arena else 'legacy'}


class PresentationRenderer:
    def __init__(self, anim, mode='arena'):
        self.mode = normalize_mode(mode)
        self.anim = anim
        info = mode_info(self.mode)
        self.width, self.height = info['width'], info['height']
        self.revision = info['render_revision']
        if self.mode == 'arena':
            if not anim.is_arena:
                raise ValueError('竞技渲染需要 arena_v1 战斗')
            from web_battle import WebBattleRenderer
            self.renderer = WebBattleRenderer(anim)
        else:
            if anim.is_arena:
                raise ValueError('经典渲染需要 base_v1 设备战斗')
            self.renderer = None

    def frame(self, seconds, *, show_cutins=True):
        return (self.renderer.frame(seconds) if self.renderer else
                self.anim.playback_frame(seconds, show_cutins=show_cutins))

    def body_frame(self, seconds, *, unit_idx=0):
        """Inspection camera on the arena's shared body track, at simulation time."""
        if self.renderer is None:
            raise ValueError('仅身体预览当前支持竞技模式')
        return self.renderer.body_frame(seconds, unit_idx=unit_idx)

    def frame_playback(self, seconds, *, show_cutins=True):
        """Audience clock: arena battles hold heavy impacts for a short dwell."""
        return (self.renderer.frame_playback(seconds) if self.renderer else
                self.anim.playback_frame(seconds, show_cutins=show_cutins))

    def playback_time(self, t):
        """Playback second at which simulation time t appears (warp inverse)."""
        return self.renderer.presentation_time(t) if self.renderer else t

    def step_view(self, seconds):
        """Advance the shared presentation view to playback second without drawing.

        Same time mapping as frame_playback; lets callers read per-frame unit
        state (team telemetry) without paying for PIL rendering. The view is
        seekable, so a later frame_playback re-syncs from any position.
        """
        if self.renderer:
            self.renderer.view._ensure(self.anim.timeline.time(self.renderer._warp(seconds)))
        else:
            self.anim._presentation_view()._ensure(self.anim.timeline.time(seconds))
        return self.anim._presentation_view()

    @property
    def metrics(self):
        if self.renderer:
            return dict(self.renderer._last_metrics)
        return dict(getattr(self.anim._presentation_view(), 'last_frame_metrics', {}))


def make_renderer(anim, mode='arena'):
    return PresentationRenderer(anim, mode)

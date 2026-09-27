"""灶台相位切换与灶温采样业务规则。"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError

DRAWING_SOFT_POINT_MAX = Decimal("95")

# 升温改保温所需的最少连续序号灶温采样数
HOLDING_MIN_TEMP_SAMPLES = 4
# 相邻序号采样的采样时刻最小间隔
TEMP_SAMPLE_MIN_GAP = timedelta(minutes=10)


def assert_can_enter_drawing(hearth) -> None:
    """
    进入「出胶」相位前：当前未收灶的 CookRun 须至少有一条
    softPointC <= 95 的 SoftPointProbe。
    """
    open_run = hearth.open_run()
    if open_run is None:
        raise ValidationError("无法进入出胶：该灶没有进行中的值守纪录。")

    ok = open_run.probes.filter(softPointC__lte=DRAWING_SOFT_POINT_MAX).exists()
    if not ok:
        raise ValidationError(
            "无法进入出胶：进行中值守尚无软化点探针 "
            f"≤ {DRAWING_SOFT_POINT_MAX}℃。"
        )


def holding_temp_readiness(run):
    """
    升温改保温的灶温采样达标判定，采样展示与改相位共用此结果。

    返回 (ok: bool, reason: str)。达标条件：
    至少 4 个连续序号采样，且窗口内相邻序号采样的采样时刻
    间隔不少于 10 分钟（按采样时刻逐差）。
    """
    samples = list(run.temp_samples.order_by("seqNo"))
    if len(samples) < HOLDING_MIN_TEMP_SAMPLES:
        return False, (
            f"升温灶温采样不足：至少需要 {HOLDING_MIN_TEMP_SAMPLES} "
            f"个连续序号采样，当前 {len(samples)} 个。"
        )

    window = samples[-HOLDING_MIN_TEMP_SAMPLES:]
    first_seq = window[0].seqNo
    seqs = [s.seqNo for s in window]
    if seqs != list(range(first_seq, first_seq + HOLDING_MIN_TEMP_SAMPLES)):
        return False, (
            f"最后 {HOLDING_MIN_TEMP_SAMPLES} 个采样序号不连续"
            f"（{seqs[0]}–{seqs[-1]} 中间有空号）。"
        )

    gap_min = int(TEMP_SAMPLE_MIN_GAP.total_seconds() // 60)
    for prev, cur in zip(window, window[1:]):
        if cur.sampledAt - prev.sampledAt < TEMP_SAMPLE_MIN_GAP:
            return False, (
                f"第 {prev.seqNo}、{cur.seqNo} 号采样时刻间隔不足 "
                f"{gap_min} 分钟（按采样时刻逐差计算）。"
            )

    return True, (
        f"灶温采样达标：{HOLDING_MIN_TEMP_SAMPLES} 个连续序号采样，"
        f"相邻间隔均不少于 {gap_min} 分钟。"
    )


def assert_can_enter_holding(hearth) -> None:
    """
    进入「保温」相位前（自升温转入）：当前未收灶 CookRun 的
    灶温采样须达标，判定口径见 holding_temp_readiness。
    """
    open_run = hearth.open_run()
    if open_run is None:
        raise ValidationError("无法进入保温：该灶没有进行中的值守纪录。")

    ok, reason = holding_temp_readiness(open_run)
    if not ok:
        raise ValidationError(f"无法进入保温：{reason}")


def assert_can_sample_temp(hearth):
    """灶温采样只允许在「升温」相位、且存在未收灶值守时进行。"""
    from apps.kiln.models import FireHearth

    open_run = hearth.open_run()
    if open_run is None:
        raise ValidationError("该灶没有进行中的值守，无法灶温采样。")
    if hearth.phase != FireHearth.PHASE_RAMPING:
        raise ValidationError(
            f"只有升温相位的值守才能灶温采样，当前为{hearth.get_phase_display()}相位。"
        )
    return open_run


def change_hearth_phase(hearth, new_phase: str):
    """统一入口：改相位时校验相位规则并保存。"""
    from apps.kiln.models import FireHearth

    if new_phase == FireHearth.PHASE_DRAWING:
        assert_can_enter_drawing(hearth)
    elif (
        new_phase == FireHearth.PHASE_HOLDING
        and hearth.phase == FireHearth.PHASE_RAMPING
    ):
        # 仅「从升温改保温」要求灶温采样达标；其它来源进保温不拦
        assert_can_enter_holding(hearth)

    hearth.phase = new_phase
    hearth.save(update_fields=["phase"])
    return hearth

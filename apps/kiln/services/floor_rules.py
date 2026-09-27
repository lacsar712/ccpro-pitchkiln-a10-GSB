"""灶台相位切换业务规则。"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError

DRAWING_SOFT_POINT_MAX = Decimal("95")

# 「升温 → 保温」灶温采样口径：至少 4 个连续序号采样点，
# 且相邻采样时刻间隔均不少于 10 分钟。
HOLDING_MIN_SAMPLES = 4
HOLDING_MIN_GAP_MINUTES = 10
HOLDING_MIN_GAP = timedelta(minutes=HOLDING_MIN_GAP_MINUTES)


def temp_sample_status(run) -> dict:
    """
    灶温采样达标口径（采样页 / 抽屉 / 改相位共用）：

    达标 = 存在至少 HOLDING_MIN_SAMPLES 个序号连续的采样点
    （如 1-2-3-4），且这些点的相邻采样时刻间隔
    （后一点 sampledAt 减前一点）均不少于 HOLDING_MIN_GAP。
    """
    samples = list(run.temp_samples.all())
    by_seq = {s.seq: s for s in samples}
    seqs = sorted(by_seq)

    ok = False
    i = 0
    while i < len(seqs) and not ok:
        # 切出一段连续序号 [i..j]
        j = i
        while j + 1 < len(seqs) and seqs[j + 1] == seqs[j] + 1:
            j += 1
        seg = seqs[i : j + 1]
        # 段内滑动取 HOLDING_MIN_SAMPLES 个连续点，核对相邻间隔
        for k in range(0, len(seg) - HOLDING_MIN_SAMPLES + 1):
            window = [by_seq[s] for s in seg[k : k + HOLDING_MIN_SAMPLES]]
            if all(
                window[n + 1].sampledAt - window[n].sampledAt >= HOLDING_MIN_GAP
                for n in range(len(window) - 1)
            ):
                ok = True
                break
        i = j + 1

    return {"count": len(samples), "ok": ok}


def assert_can_sample(run) -> None:
    """登记灶温采样前：仅升温相位的所属值守可采样，其它相位拒绝。"""
    if run.hearth.phase != run.hearth.PHASE_RAMPING:
        raise ValidationError(
            f"仅升温相位的值守可登记灶温采样，"
            f"当前为「{run.hearth.get_phase_display()}」，已拒绝。"
        )


def assert_can_enter_holding(hearth) -> None:
    """
    「升温 → 保温」前：当前未收灶 CookRun 的灶温采样须达标
    （见 temp_sample_status 口径）。
    """
    open_run = hearth.open_run()
    if open_run is None:
        raise ValidationError(
            {"phase": "无法进入保温：该灶没有进行中的值守纪录，无法核对灶温采样。"}
        )

    status = temp_sample_status(open_run)
    if not status["ok"]:
        raise ValidationError(
            {
                "phase": (
                    "无法进入保温：灶温采样不足 — 需至少 "
                    f"{HOLDING_MIN_SAMPLES} 个连续序号采样点，且相邻采样时刻"
                    f"间隔不少于 {HOLDING_MIN_GAP_MINUTES} 分钟"
                    f"（当前 {status['count']} 点）。"
                )
            }
        )


def assert_can_enter_drawing(hearth) -> None:
    """
    进入「出胶」相位前：当前未收灶的 CookRun 须至少有一条
    softPointC <= 95 的 SoftPointProbe。
    """
    open_run = hearth.open_run()
    if open_run is None:
        raise ValidationError(
            {"phase": "无法进入出胶：该灶没有进行中的值守纪录。"}
        )

    ok = open_run.probes.filter(softPointC__lte=DRAWING_SOFT_POINT_MAX).exists()
    if not ok:
        raise ValidationError(
            {
                "phase": (
                    "无法进入出胶：进行中值守尚无软化点探针 "
                    f"≤ {DRAWING_SOFT_POINT_MAX}℃。"
                )
            }
        )


def change_hearth_phase(hearth, new_phase: str):
    """统一入口：改相位时校验出胶 / 保温规则并保存。"""
    from apps.kiln.models import FireHearth

    if new_phase == FireHearth.PHASE_DRAWING:
        assert_can_enter_drawing(hearth)
    if (
        hearth.phase == FireHearth.PHASE_RAMPING
        and new_phase == FireHearth.PHASE_HOLDING
    ):
        assert_can_enter_holding(hearth)

    hearth.phase = new_phase
    hearth.save(update_fields=["phase"])
    return hearth

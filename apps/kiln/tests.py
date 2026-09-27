from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import CookRun, FireHearth, HearthTempSample, ResinLot
from .services.floor_rules import (
    assert_can_enter_drawing,
    assert_can_enter_holding,
    assert_can_sample_temp,
    change_hearth_phase,
    holding_temp_readiness,
)


class TempSampleRuleTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.lot = ResinLot.objects.create(
            lotCode="脂-测试-0001",
            originPlace="松脂坳",
            arrivalKg=Decimal("100.00"),
            receivedAt=now - timedelta(days=1),
        )
        self.hearth = FireHearth.objects.create(
            lane=1, tag="测试-灶甲", resinGrade="特级脂",
            phase=FireHearth.PHASE_RAMPING,
        )
        self.run = CookRun.objects.create(
            hearth=self.hearth,
            resinLot=self.lot,
            openedAt=now - timedelta(hours=2),
            targetSoftPointC=Decimal("88.00"),
        )
        self.t0 = timezone.now() - timedelta(minutes=40)

    def _sample(self, seq, minutes_ago, temp=Decimal("170.00")):
        return HearthTempSample.objects.create(
            run=self.run,
            seqNo=seq,
            tempC=temp,
            sampledAt=self.t0 + timedelta(minutes=40 - minutes_ago),
            recorderName="测试员",
        )

    def test_sample_allowed_only_in_ramping(self):
        self.assertEqual(assert_can_sample_temp(self.hearth), self.run)
        for phase in (
            FireHearth.PHASE_COLD,
            FireHearth.PHASE_CHARGING,
            FireHearth.PHASE_HOLDING,
            FireHearth.PHASE_DRAWING,
        ):
            self.hearth.phase = phase
            with self.assertRaises(ValidationError):
                assert_can_sample_temp(self.hearth)

    def test_sample_requires_open_run(self):
        self.run.closedAt = timezone.now()
        self.run.save()
        with self.assertRaises(ValidationError):
            assert_can_sample_temp(self.hearth)

    def test_temp_must_be_positive(self):
        s = HearthTempSample(
            run=self.run, seqNo=1, tempC=Decimal("0"),
            sampledAt=self.t0, recorderName="测试员",
        )
        with self.assertRaises(ValidationError) as ctx:
            s.full_clean()
        self.assertIn("tempC", ctx.exception.message_dict)

    def test_seq_unique_per_run(self):
        self._sample(1, 30)
        dup = HearthTempSample(
            run=self.run, seqNo=1, tempC=Decimal("180.00"),
            sampledAt=self.t0 + timedelta(minutes=20), recorderName="测试员",
        )
        with self.assertRaises(ValidationError):
            dup.full_clean()

    def test_holding_needs_four_samples(self):
        self._sample(1, 31)
        self._sample(2, 20)
        ok, reason = holding_temp_readiness(self.run)
        self.assertFalse(ok)
        self.assertIn("不足", reason)
        with self.assertRaises(ValidationError):
            assert_can_enter_holding(self.hearth)

    def test_holding_rejects_gap_under_ten_minutes(self):
        # 第 2、3 点只隔 5 分钟
        self._sample(1, 35)
        self._sample(2, 25)
        self._sample(3, 20)
        self._sample(4, 10)
        ok, reason = holding_temp_readiness(self.run)
        self.assertFalse(ok)
        self.assertIn("间隔", reason)
        with self.assertRaises(ValidationError) as ctx:
            assert_can_enter_holding(self.hearth)
        self.assertIn("10 分钟", ctx.exception.messages[0])

    def test_holding_rejects_non_contiguous_seqs(self):
        self._sample(1, 50)
        self._sample(2, 38)
        self._sample(4, 26)
        self._sample(5, 14)
        ok, reason = holding_temp_readiness(self.run)
        self.assertFalse(ok)
        self.assertIn("不连续", reason)

    def test_holding_passes_with_four_continuous_spaced_samples(self):
        self._sample(1, 40)
        self._sample(2, 29)
        self._sample(3, 18)
        self._sample(4, 7)
        ok, reason = holding_temp_readiness(self.run)
        self.assertTrue(ok, reason)
        assert_can_enter_holding(self.hearth)  # 不抛异常
        change_hearth_phase(self.hearth, FireHearth.PHASE_HOLDING)
        self.hearth.refresh_from_db()
        self.assertEqual(self.hearth.phase, FireHearth.PHASE_HOLDING)

    def test_ramping_to_holding_blocked_by_service(self):
        self._sample(1, 30)
        with self.assertRaises(ValidationError):
            change_hearth_phase(self.hearth, FireHearth.PHASE_HOLDING)
        self.hearth.refresh_from_db()
        self.assertEqual(self.hearth.phase, FireHearth.PHASE_RAMPING)

    def test_drawing_rule_still_enforced(self):
        with self.assertRaises(ValidationError):
            assert_can_enter_drawing(self.hearth)
        with self.assertRaises(ValidationError):
            change_hearth_phase(self.hearth, FireHearth.PHASE_DRAWING)


from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402


class TempSampleViewTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("worker", password="123456")
        self.client.force_login(user)
        now = timezone.now()
        self.lot = ResinLot.objects.create(
            lotCode="脂-视图-0001",
            originPlace="桐油坑",
            arrivalKg=Decimal("100.00"),
            receivedAt=now - timedelta(days=1),
        )
        self.hearth = FireHearth.objects.create(
            lane=1, tag="视图-灶甲", resinGrade="一级脂",
            phase=FireHearth.PHASE_RAMPING,
        )
        self.run = CookRun.objects.create(
            hearth=self.hearth, resinLot=self.lot,
            openedAt=now - timedelta(hours=2),
            targetSoftPointC=Decimal("90.00"),
        )

    def _post_sample(self, when, temp="170.00"):
        return self.client.post(
            f"/hearth/{self.hearth.pk}/temp-sample/",
            {"sampledAt": when.strftime("%Y-%m-%dT%H:%M"),
             "tempC": temp, "recorderName": "值守阿坤"},
        )

    def test_sample_post_autoincrements_seq(self):
        now = timezone.localtime()
        r1 = self._post_sample(now - timedelta(minutes=30))
        self.assertEqual(r1.status_code, 302)
        r2 = self._post_sample(now - timedelta(minutes=15))
        self.assertEqual(r2.status_code, 302)
        seqs = list(
            self.run.temp_samples.order_by("seqNo").values_list("seqNo", flat=True)
        )
        self.assertEqual(seqs, [1, 2])

    def test_sample_post_rejects_non_ramping_and_nonpositive(self):
        # 非升温相位拒绝
        self.hearth.phase = FireHearth.PHASE_HOLDING
        self.hearth.save(update_fields=["phase"])
        resp = self._post_sample(timezone.localtime())
        self.assertEqual(HearthTempSample.objects.count(), 0)
        self.assertEqual(resp.status_code, 302)

        # 回到升温，灶温非正也拒绝
        self.hearth.phase = FireHearth.PHASE_RAMPING
        self.hearth.save(update_fields=["phase"])
        self._post_sample(timezone.localtime(), temp="-3")
        self.assertEqual(HearthTempSample.objects.count(), 0)

    def test_phase_change_ramping_to_holding_blocked_then_allowed(self):
        now = timezone.localtime()
        url = f"/hearth/{self.hearth.pk}/phase/"
        # 种子式两点：拒绝
        self._post_sample(now - timedelta(minutes=25), "162.50")
        self._post_sample(now - timedelta(minutes=12), "171.20")
        resp = self.client.post(url, {"phase": FireHearth.PHASE_HOLDING})
        self.assertEqual(resp.status_code, 302)
        self.hearth.refresh_from_db()
        self.assertEqual(self.hearth.phase, FireHearth.PHASE_RAMPING)

        # 补够四点、间隔均 >=10 分钟：放行
        self._post_sample(now - timedelta(minutes=1), "176.00")
        # 目前三点；再补一点且与第 3 点间隔 >=10（now-1 与 now+9 间隔 10）
        self._post_sample(now + timedelta(minutes=9), "179.00")
        resp = self.client.post(url, {"phase": FireHearth.PHASE_HOLDING})
        self.assertEqual(resp.status_code, 302)
        self.hearth.refresh_from_db()
        self.assertEqual(self.hearth.phase, FireHearth.PHASE_HOLDING)

    def test_drawer_shows_sample_count(self):
        HearthTempSample.objects.create(
            run=self.run, seqNo=1, tempC=Decimal("170.00"),
            sampledAt=timezone.now(), recorderName="阿坤",
        )
        resp = self.client.get(f"/hearth/{self.hearth.pk}/drawer/")
        self.assertEqual(resp.status_code, 302)  # 非 htmx 跳转看板
        resp = self.client.get(
            f"/?hearth={self.hearth.pk}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("采样点数 1", body)
        self.assertIn("今日", body)  # 班次条统计 title


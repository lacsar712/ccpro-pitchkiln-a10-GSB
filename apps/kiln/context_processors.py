from django.utils import timezone

from .models import HearthTempSample


def shift_strip(request):
    """班次条全局数据：当班（今日）灶温采样点数。"""
    today = timezone.localdate()
    temp_sample_today = HearthTempSample.objects.filter(
        sampledAt__date=today
    ).count()
    return {"temp_sample_today": temp_sample_today}

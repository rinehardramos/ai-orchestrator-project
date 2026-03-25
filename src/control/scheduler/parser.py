"""
Cron Expression Parser

Parses and evaluates cron expressions using croniter.
Supports standard 5-field cron format and timezone-aware evaluation.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from croniter import croniter

logger = logging.getLogger(__name__)


def validate_cron(expression: str) -> bool:
    """
    Validate a cron expression.
    
    Args:
        expression: Cron expression string (5 fields)
        
    Returns:
        True if valid, False otherwise
    """
    if not expression or not isinstance(expression, str):
        return False
    
    try:
        croniter(expression)
        return True
    except (ValueError, KeyError) as e:
        logger.debug(f"Invalid cron expression '{expression}': {e}")
        return False


def get_next_run(
    expression: str,
    timezone: str = "UTC",
    from_time: Optional[datetime] = None
) -> Optional[datetime]:
    """
    Get the next run time for a cron expression.
    
    Args:
        expression: Cron expression string
        timezone: Timezone for evaluation (default: UTC)
        from_time: Starting point (default: now)
        
    Returns:
        Next run datetime or None if invalid
    """
    if not validate_cron(expression):
        return None
    
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        logger.warning(f"Invalid timezone '{timezone}', using UTC")
        tz = ZoneInfo("UTC")
    
    if from_time is None:
        from_time = datetime.now(tz)
    elif from_time.tzinfo is None:
        from_time = from_time.replace(tzinfo=tz)
    
    try:
        cron = croniter(expression, from_time)
        next_run = cron.get_next(datetime)
        return next_run
    except Exception as e:
        logger.error(f"Failed to get next run for '{expression}': {e}")
        return None


def get_next_runs(
    expression: str,
    count: int = 5,
    timezone: str = "UTC",
    from_time: Optional[datetime] = None
) -> List[datetime]:
    """
    Get the next N run times for a cron expression.
    
    Args:
        expression: Cron expression string
        count: Number of run times to return
        timezone: Timezone for evaluation
        from_time: Starting point
        
    Returns:
        List of upcoming run datetimes
    """
    if not validate_cron(expression):
        return []
    
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    
    if from_time is None:
        from_time = datetime.now(tz)
    elif from_time.tzinfo is None:
        from_time = from_time.replace(tzinfo=tz)
    
    try:
        cron = croniter(expression, from_time)
        return [cron.get_next(datetime) for _ in range(count)]
    except Exception as e:
        logger.error(f"Failed to get next runs for '{expression}': {e}")
        return []


def get_human_description(expression: str) -> str:
    """
    Get a human-readable description of a cron expression.
    
    Args:
        expression: Cron expression string
        
    Returns:
        Human-readable description
    """
    if not validate_cron(expression):
        return "Invalid expression"
    
    parts = expression.split()
    if len(parts) != 5:
        return f"Cron: {expression}"
    
    minute, hour, day, month, weekday = parts
    
    descriptions = []
    
    if minute == "*" and hour == "*":
        descriptions.append("Every minute")
    elif minute == "0" and hour == "*":
        descriptions.append("Every hour")
    elif minute.isdigit() and hour == "*":
        descriptions.append(f"Every hour at minute {minute}")
    elif minute.isdigit() and hour.isdigit():
        descriptions.append(f"At {hour.zfill(2)}:{minute.zfill(2)}")
    
    if weekday != "*":
        days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        if weekday.isdigit():
            descriptions.append(f"on {days[int(weekday)]}")
        elif "-" in weekday:
            descriptions.append(f"on weekdays")
    
    if day != "*" and day.isdigit():
        descriptions.append(f"on day {day}")
    
    if month != "*" and month.isdigit():
        months = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        if int(month) <= 12:
            descriptions.append(f"in {months[int(month) - 1]}")
    
    if not descriptions:
        return f"Cron: {expression}"
    
    return " ".join(descriptions)


def parse_interval(interval_seconds: int) -> str:
    """
    Convert interval in seconds to human-readable format.
    
    Args:
        interval_seconds: Interval in seconds
        
    Returns:
        Human-readable interval string
    """
    if interval_seconds < 60:
        return f"Every {interval_seconds} seconds"
    elif interval_seconds < 3600:
        minutes = interval_seconds // 60
        return f"Every {minutes} minute{'s' if minutes > 1 else ''}"
    elif interval_seconds < 86400:
        hours = interval_seconds // 3600
        return f"Every {hours} hour{'s' if hours > 1 else ''}"
    else:
        days = interval_seconds // 86400
        return f"Every {days} day{'s' if days > 1 else ''}"


def calculate_next_run_at(
    schedule_type: str,
    cron_expression: Optional[str] = None,
    interval_seconds: Optional[int] = None,
    scheduled_for: Optional[datetime] = None,
    timezone: str = "UTC",
    last_run_at: Optional[datetime] = None
) -> Optional[datetime]:
    """
    Calculate the next run time based on schedule type.
    
    Args:
        schedule_type: 'cron', 'interval', or 'once'
        cron_expression: Cron expression (for cron type)
        interval_seconds: Interval in seconds (for interval type)
        scheduled_for: Scheduled time (for once type)
        timezone: Timezone for evaluation
        last_run_at: Last execution time
        
    Returns:
        Next run datetime or None
    """
    if schedule_type == "cron":
        return get_next_run(cron_expression or "", timezone)
    
    elif schedule_type == "interval":
        if not interval_seconds:
            return None
        tz = ZoneInfo(timezone)
        base = last_run_at or datetime.now(tz)
        if base.tzinfo is None:
            base = base.replace(tzinfo=tz)
        return base + timedelta(seconds=interval_seconds)
    
    elif schedule_type == "once":
        return scheduled_for
    
    return None


class CronSchedule:
    """Helper class for working with cron schedules."""
    
    def __init__(self, expression: str, timezone: str = "UTC"):
        if not validate_cron(expression):
            raise ValueError(f"Invalid cron expression: {expression}")
        self.expression = expression
        self.timezone = timezone
        self._croniter = None
    
    def _get_croniter(self, from_time: Optional[datetime] = None):
        """Get or create croniter instance."""
        tz = ZoneInfo(self.timezone)
        if from_time is None:
            from_time = datetime.now(tz)
        elif from_time.tzinfo is None:
            from_time = from_time.replace(tzinfo=tz)
        return croniter(self.expression, from_time)
    
    def get_next(self, from_time: Optional[datetime] = None) -> datetime:
        """Get next run time."""
        cron = self._get_croniter(from_time)
        return cron.get_next(datetime)
    
    def get_prev(self, from_time: Optional[datetime] = None) -> datetime:
        """Get previous run time."""
        cron = self._get_croniter(from_time)
        return cron.get_prev(datetime)
    
    def get_next_n(self, n: int, from_time: Optional[datetime] = None) -> List[datetime]:
        """Get next N run times."""
        cron = self._get_croniter(from_time)
        return [cron.get_next(datetime) for _ in range(n)]
    
    def is_due(self, last_run: Optional[datetime] = None) -> bool:
        """Check if schedule is due."""
        next_run = self.get_next(last_run)
        return next_run <= datetime.now(next_run.tzinfo)
    
    @property
    def description(self) -> str:
        """Get human-readable description."""
        return get_human_description(self.expression)

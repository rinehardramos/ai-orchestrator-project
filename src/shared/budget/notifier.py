import logging
from typing import Optional
from datetime import datetime

from .models import UsageRecord, BudgetCheck

logger = logging.getLogger(__name__)


class BudgetNotifier:
    def __init__(self, telegram_notifier=None):
        self.telegram_notifier = telegram_notifier
    
    async def send_budget_alert(self, check: BudgetCheck, usage: UsageRecord):
        message = self._format_alert_message(check, usage)
        
        print(f"\n{'='*60}")
        print(message)
        print(f"{'='*60}\n")
        
        if self.telegram_notifier:
            try:
                telegram_message = self._format_telegram_message(check, usage)
                await self.telegram_notifier.send_message(telegram_message)
            except Exception as e:
                logger.error(f"Failed to send Telegram notification: {e}")
    
    def _format_alert_message(self, check: BudgetCheck, usage: UsageRecord) -> str:
        lines = [
            "⚠️  BUDGET ALERT  ⚠️",
            "",
            f"Provider: {check.provider.upper()}",
            f"Spent: ${check.provider_spent:.4f} / ${check.provider_limit:.2f} ({check.provider_pct*100:.1f}%)",
            f"Threshold: {check.threshold*100:.0f}%",
        ]
        
        if check.model_id:
            lines.extend([
                "",
                f"Model: {check.model_id}",
                f"Model spent: ${check.model_spent:.4f}" + (f" / ${check.model_limit:.2f}" if check.model_limit else ""),
            ])
        
        lines.extend([
            "",
            f"Remaining: ${check.provider_limit - check.provider_spent:.2f}",
            "",
            f"Last task: {usage.task_id}",
            f"Last cost: ${usage.cost_usd:.4f} ({usage.total_tokens} tokens)",
        ])
        
        return "\n".join(lines)
    
    def _format_telegram_message(self, check: BudgetCheck, usage: UsageRecord) -> str:
        lines = [
            "⚠️ *Budget Alert*",
            "",
            f"Provider: `{check.provider}`",
            f"Spent: `${check.provider_spent:.2f} / ${check.provider_limit:.2f}`",
            f"Used: `{check.provider_pct*100:.1f}%`",
            "",
            f"Remaining: `${check.provider_limit - check.provider_spent:.2f}`",
        ]
        
        if check.model_id:
            lines.extend([
                "",
                f"Model: `{check.model_id}`",
                f"Model spent: `${check.model_spent:.2f}`",
            ])
        
        return "\n".join(lines)
    
    def format_status_output(self, status: dict) -> str:
        lines = ["📊 Budget Status", ""]
        
        for provider, data in status.items():
            if "error" in data:
                lines.append(f"{provider}: Error - {data['error']}")
                continue
            
            status_icon = "✅" if data.get("status") == "ok" else "⚠️"
            lines.extend([
                f"{status_icon} {provider.upper()}",
                f"   Spent: ${data['spent']:.4f} / ${data['limit']:.2f}",
                f"   Used: {data['pct_used']*100:.1f}%",
            ])
            
            if data.get("remaining") is not None:
                lines.append(f"   Remaining: ${data['remaining']:.2f}")
            
            if "model" in data:
                lines.append(f"   Model ({data['model']['model_id']}): ${data['model']['spent']:.4f}, {data['model']['tokens']} tokens")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def format_pipeline_stats(self, stats: list) -> str:
        if not stats:
            return "No pipeline stats available."
        
        lines = [
            "📈 Pipeline Stage Statistics",
            "",
            "| Stage | Tasks | Tokens | Cost |",
            "|-------|-------|--------|------|",
        ]
        
        total_cost = sum(s.get("total_cost", 0) or 0 for s in stats)
        
        for stat in stats:
            stage = stat.get("pipeline_stage", "unknown")
            tasks = stat.get("total_tasks", 0)
            tokens = stat.get("total_tokens", 0)
            cost = stat.get("total_cost", 0) or 0
            pct = (cost / total_cost * 100) if total_cost > 0 else 0
            
            lines.append(f"| {stage} | {tasks} | {tokens} | ${cost:.4f} ({pct:.0f}%) |")
        
        lines.extend([
            "",
            f"Total cost: ${total_cost:.4f}",
        ])
        
        return "\n".join(lines)

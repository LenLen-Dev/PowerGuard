"""Email notifier implementation."""

from __future__ import annotations

import html
import logging
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage

from app.notifiers.base import Notifier
from app.timezone_utils import BEIJING_TZ

logger = logging.getLogger(__name__)


class EmailNotifierError(RuntimeError):
    """Raised when email notification fails."""


class EmailNotifier(Notifier):
    """Send alerts through SMTP email."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        use_tls: bool,
        username: str,
        password: str,
        sender: str,
        recipient: str,
        timeout_seconds: int,
    ) -> None:
        if not smtp_host:
            raise ValueError("SMTP host is required")
        if smtp_port <= 0:
            raise ValueError("SMTP port must be greater than 0")
        if not username or not password:
            raise ValueError("SMTP username and password are required")
        if not sender or not recipient:
            raise ValueError("Email sender and recipient are required")

        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._use_tls = use_tls
        self._username = username
        self._password = password
        self._sender = sender
        self._recipient = recipient
        self._timeout_seconds = timeout_seconds

    def send(self, title: str, message: str) -> None:
        if self._is_quiet_hours_beijing():
            logger.warning(
                "Email suppressed during quiet hours (BJT 00:00-08:00): title=%s",
                title,
            )
            return

        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = self._sender
        msg["To"] = self._recipient
        msg.set_content(message)
        msg.add_alternative(self._build_html_content(title=title, message=message), subtype="html")

        try:
            with smtplib.SMTP(
                self._smtp_host,
                self._smtp_port,
                timeout=self._timeout_seconds,
            ) as smtp:
                smtp.ehlo()
                if self._use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(self._username, self._password)
                smtp.send_message(msg)
        except smtplib.SMTPException as exc:
            logger.exception("Email notification failed")
            raise EmailNotifierError(f"Email notification failed: {exc}") from exc
        except OSError as exc:
            logger.exception("SMTP connection failed")
            raise EmailNotifierError(f"SMTP connection failed: {exc}") from exc

        logger.info("Email notification sent successfully")

    def _build_html_content(self, title: str, message: str) -> str:
        fields = self._parse_fields(message)
        project = fields.get("项目", "--")
        room = fields.get("房间", "--")
        account = fields.get("账号", "--")
        today_usage = fields.get("今日耗电量")
        api_message = fields.get("接口提示", "--")
        query_time = (
            fields.get("查询时间(北京时间)")
            or fields.get("查询时间(BJT)")
            or fields.get("查询时间(UTC)")
            or "--"
        )

        balance_text = fields.get("当前剩余电量", "--")
        if balance_text != "--" and "kWh" not in balance_text:
            balance_text = f"{balance_text} kWh"

        title_tokens = ("预警", "告警", "过低", "低电量")
        is_low_alert = any(token in title for token in title_tokens)

        balance_color = "#EF4444" if is_low_alert else "#10B981"
        balance_num = self._parse_balance_number(balance_text)
        if not is_low_alert and balance_num is not None and balance_num <= 20:
            balance_color = "#EF4444"
        elif not is_low_alert and balance_num is not None and balance_num <= 40:
            balance_color = "#F59E0B"

        header_bg = "#EF4444" if is_low_alert else "#3B82F6"
        header_icon = "⚠" if is_low_alert else "⚡"
        notice_bg = "#FEE2E2" if is_low_alert else "#FEF3C7"
        notice_color = "#991B1B" if is_low_alert else "#92400E"
        notice_text = (
            "⚠ 电量处于低位，请尽快处理，避免影响正常用电。"
            if is_low_alert
            else "⚠ 请留意电量使用情况，避免因电量不足影响正常用电。"
        )

        return f"""
<div style="font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial; background-color:#f5f7fb; padding:20px;">
  <div style="max-width:600px; margin:auto; background:#ffffff; border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,0.05); overflow:hidden;">
    <div style="background:{header_bg}; color:#ffffff; padding:16px 20px; font-size:18px;">
      {header_icon} {html.escape(title)}
    </div>

    <div style="padding:20px;">
      <p style="margin:0 0 10px; font-size:14px; color:#6b7280;">
        以下是最新电量监控信息：
      </p>

      <div style="margin:20px 0; text-align:center;">
        <div style="font-size:14px; color:#6b7280;">当前剩余电量</div>
        <div style="font-size:36px; font-weight:bold; color:{balance_color};">
          {html.escape(balance_text)}
        </div>
      </div>

      <table style="width:100%; font-size:14px; border-collapse:collapse;">
        <tr>
          <td style="padding:8px 0; color:#6b7280;">项目</td>
          <td style="padding:8px 0; text-align:right; color:#111827;">{html.escape(project)}</td>
        </tr>
        <tr>
          <td style="padding:8px 0; color:#6b7280;">房间</td>
          <td style="padding:8px 0; text-align:right;">{html.escape(room)}</td>
        </tr>
        <tr>
          <td style="padding:8px 0; color:#6b7280;">账号</td>
          <td style="padding:8px 0; text-align:right;">{html.escape(account)}</td>
        </tr>
        {self._optional_row("今日耗电量", today_usage)}
        <tr>
          <td style="padding:8px 0; color:#6b7280;">接口提示</td>
          <td style="padding:8px 0; text-align:right;">{html.escape(api_message)}</td>
        </tr>
        <tr>
          <td style="padding:8px 0; color:#6b7280;">查询时间</td>
          <td style="padding:8px 0; text-align:right;">{html.escape(query_time)}</td>
        </tr>
      </table>

      <div style="margin-top:20px; padding:12px; background:{notice_bg}; color:{notice_color}; border-radius:6px; font-size:13px;">
        {html.escape(notice_text)}
      </div>
    </div>

    <div style="background:#f9fafb; padding:12px 20px; font-size:12px; color:#9ca3af; text-align:center;">
      本邮件由 PowerGuard 自动发送
    </div>
  </div>
</div>
""".strip()

    @staticmethod
    def _parse_fields(message: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for raw_line in message.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = re.split(r"[：:]", line, maxsplit=1)
            if len(parts) != 2:
                continue
            key = parts[0].strip()
            value = parts[1].strip()
            if key:
                fields[key] = value
        return fields

    @staticmethod
    def _parse_balance_number(balance_text: str) -> float | None:
        match = re.search(r"([+-]?\d+(?:\.\d+)?)", balance_text or "")
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _optional_row(label: str, value: str | None) -> str:
        if value is None or not value.strip():
            return ""
        safe_label = html.escape(label)
        safe_value = html.escape(value.strip())
        return (
            "<tr>"
            f"<td style='padding:8px 0; color:#6b7280;'>{safe_label}</td>"
            f"<td style='padding:8px 0; text-align:right;'>{safe_value}</td>"
            "</tr>"
        )

    @staticmethod
    def _is_quiet_hours_beijing(now_bj: datetime | None = None) -> bool:
        current_bj = now_bj or datetime.now(BEIJING_TZ)
        seconds_since_midnight = (
            current_bj.hour * 3600
            + current_bj.minute * 60
            + current_bj.second
            + current_bj.microsecond / 1_000_000
        )
        return 0 <= seconds_since_midnight <= 8 * 3600
        # return 0 <= seconds_since_midnight <= 86399

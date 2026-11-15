"""HTML-шаблоны страницы оплаты на домене проекта.

Страница открывается по ``GET /pay/<payment_id>`` и выглядит как
самостоятельный брендированный экран, а не «голый» ЮKassa. Работает
и в браузере, и внутри мини-приложения MAX (``open_app``).
"""

from __future__ import annotations

import html

#: Базовый шаблон: градиентный фон + белая карточка по центру.
_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<style>
  :root {{
    --brand: #2f9e8f;
    --brand-dark: #248073;
    --text: #1f2b2a;
    --muted: #6b7c7a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
    background: linear-gradient(135deg, #7fd4cf 0%, #4bb3a6 55%, #2f9e8f 100%);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    color: var(--text);
  }}
  .card {{
    width: 100%;
    max-width: 420px;
    background: #fff;
    border-radius: 18px;
    padding: 28px 24px 24px;
    box-shadow: 0 18px 44px rgba(12, 62, 56, .28);
    text-align: center;
  }}
  .logo {{
    width: 64px; height: 64px; margin: 0 auto 14px;
    border-radius: 50%;
    background: linear-gradient(160deg, #e9f6f4, #cfeae6);
    display: flex; align-items: center; justify-content: center;
    font-size: 30px;
  }}
  h1 {{ font-size: 21px; margin: 0 0 6px; }}
  .subtitle {{ color: var(--muted); font-size: 14px; margin: 0 0 20px; }}
  .amount {{
    font-size: 40px; font-weight: 700; letter-spacing: -.5px;
    margin: 4px 0 2px;
  }}
  .amount-note {{ color: var(--muted); font-size: 13px; margin-bottom: 22px; }}
  .features {{
    text-align: left; font-size: 14px; line-height: 1.65;
    background: #f7fbfa; border-radius: 12px;
    padding: 14px 16px; margin-bottom: 22px; color: #2b3a39;
  }}
  ul {{ padding-left: 20px; margin: 0; }}
  .features li {{ margin: 2px 0; }}
  .btn {{
    display: block; width: 100%;
    padding: 15px 18px;
    border: 0; border-radius: 12px;
    background: var(--brand); color: #fff;
    font-size: 17px; font-weight: 600;
    text-decoration: none; cursor: pointer;
    transition: background .18s ease, transform .06s ease;
  }}
  .btn:hover {{ background: var(--brand-dark); }}
  .btn:active {{ transform: translateY(1px); }}
  .btn-secondary {{
    display: inline-block; margin-top: 14px;
    color: var(--muted); font-size: 13px; text-decoration: none;
    border-bottom: 1px dashed currentColor;
  }}
  .status {{ font-size: 46px; margin-bottom: 8px; }}
  .notice {{
    background: #fff4e5;
    border-left: 4px solid #f0a020;
    border-radius: 8px;
    padding: 11px 14px;
    margin-bottom: 18px;
    font-size: 14px;
    font-weight: 600;
    color: #8a5a00;
    text-align: left;
    line-height: 1.45;
  }}
  .footer {{
    margin-top: 20px; padding-top: 14px;
    border-top: 1px solid #eef3f2;
    color: var(--muted); font-size: 12px;
  }}
</style>
</head>
<body>
  <div class="card">{content}</div>
</body>
</html>
"""

_PAY_CONTENT = """
  <div class="logo">👛</div>
  <h1>Оплата подписки</h1>
  <p class="subtitle">«Умный кошелёк» — AI-функции без ограничений</p>

  <div class="amount">{amount}</div>
  <div class="amount-note">{days} дней доступа</div>

  <div class="features">
    <ul>
      <li>неограниченный разбор текста и голоса;</li>
      <li>несколько операций в одном сообщении;</li>
      <li>AI-помощник по вашим финансам;</li>
      <li>новые AI-функции по мере появления.</li>
    </ul>
  </div>

  <a class="btn" href="{payment_url}">Оплатить {amount}</a>
  <a class="btn-secondary" href="{payment_url}" target="_blank" rel="noopener">
    Открыть в браузере
  </a>

  <div class="notice">⚠️ ВАЖНО: при оплате отключите VPN</div>

  <div class="footer">
    Оплата через ЮKassa · карта, СБП, ЮMoney<br>
    Подписка активируется автоматически после оплаты
  </div>
"""

_NOT_FOUND_CONTENT = """
  <div class="status">🔎</div>
  <h1>Счёт не найден</h1>
  <p class="subtitle">
    Возможно, ссылка устарела. Откройте бота и создайте новый счёт.
  </p>
"""

_PAID_CONTENT = """
  <div class="status">✅</div>
  <h1>Оплата прошла</h1>
  <p class="subtitle">
    Подписка активирована. Вернитесь в MAX — бот уже знает об оплате.
  </p>
"""

_CANCEL_CONTENT = """
  <div class="status">↩️</div>
  <h1>Оплата отменена</h1>
  <p class="subtitle">
    Платёж не был завершён. Вернитесь в бота и попробуйте снова.
  </p>
"""

_ERROR_CONTENT = """
  <div class="status">⚠️</div>
  <h1>Не удалось открыть оплату</h1>
  <p class="subtitle">
    Попробуйте ещё раз из бота или напишите владельцу.
  </p>
"""


def render_page(title: str, content: str) -> str:
    """Собрать HTML-страницу с брендингом."""
    return _PAGE.format(title=html.escape(title), content=content)


def render_payment_page(amount_text: str, days: int, payment_url: str) -> str:
    """Страница с кнопкой оплаты."""
    content = _PAY_CONTENT.format(
        amount=html.escape(amount_text),
        days=int(days),
        payment_url=html.escape(payment_url, quote=True),
    )
    return render_page("Оплата подписки — Умный кошелёк", content)


def render_not_found_page() -> str:
    return render_page("Счёт не найден — Умный кошелёк", _NOT_FOUND_CONTENT)


def render_paid_page() -> str:
    return render_page("Оплата прошла — Умный кошелёк", _PAID_CONTENT)


def render_cancel_page() -> str:
    return render_page("Оплата отменена — Умный кошелёк", _CANCEL_CONTENT)


def render_error_page() -> str:
    return render_page("Ошибка оплаты — Умный кошелёк", _ERROR_CONTENT)

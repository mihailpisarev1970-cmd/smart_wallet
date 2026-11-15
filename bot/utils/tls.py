"""Настройка TLS для обращения к MAX API.

Сервер ``platform-api2.max.ru`` предъявляет сертификат, выпущенный
«Russian Trusted Sub CA» → «Russian Trusted Root CA» (НУЦ Минцифры России).
Python доверяет только набору из ``certifi``, поэтому без дополнительной
настройки получаем::

    [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
    unable to get local issuer certificate

Правильное решение (без отключения проверки сертификата!) — добавить
корневые сертификаты Минцифры в доверенные:

* ``certs/ru_trusted/*.pem`` — официальные сертификаты с gu-st.ru;
* ``ensure_ca_bundle()`` собирает ``combined_bundle.pem`` = certifi + Минцифры;
* на Linux-сервере также используется системное хранилище
  (``/etc/ssl/certs/ca-certificates.crt``), где сертификат Минцифры
  может быть уже предустановлен.

Модуль не импортирует Django и не зависит от настроек бота.
"""

from __future__ import annotations

import logging
import ssl
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RU_CA_DIR = PROJECT_ROOT / "certs" / "ru_trusted"
COMBINED_BUNDLE = RU_CA_DIR / "combined_bundle.pem"

#: Системные PEM-бандлы, которые могут содержать сертификат Минцифры.
SYSTEM_CA_BUNDLES = (
    Path("/etc/ssl/certs/ca-certificates.crt"),
    Path("/etc/pki/tls/certs/ca-bundle.crt"),
    Path("/etc/ssl/cert.pem"),
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def build_ca_bundle(force: bool = False) -> str:
    """Собрать PEM-бандл (certifi + сертификаты Минцифры) и вернуть путь.

    Файл кэшируется: пересобирается только если его нет или ``force=True``.
    Если пересобрать не удалось (например, нет прав на запись), возвращается
    путь к сертификату из ``certifi`` — бот продолжит работу и сможет
    подключиться к сервисам, которые не требуют сертификата Минцифры.
    """
    import certifi

    if COMBINED_BUNDLE.exists() and not force:
        return str(COMBINED_BUNDLE)

    parts = [_read(Path(certifi.where()))]
    ru_certs = sorted(RU_CA_DIR.glob("*.pem"))
    for pem_file in ru_certs:
        if pem_file.name == COMBINED_BUNDLE.name:
            continue
        content = _read(pem_file)
        if "BEGIN CERTIFICATE" in content:
            parts.append(content)

    if not ru_certs:
        logger.warning(
            "Сертификаты Минцифры не найдены в %s — запросы к MAX API могут "
            "завершаться ошибкой TLS. Добавьте russian_trusted_root_ca.pem.",
            RU_CA_DIR,
        )
        return certifi.where()

    try:
        RU_CA_DIR.mkdir(parents=True, exist_ok=True)
        COMBINED_BUNDLE.write_text("\n".join(parts), encoding="utf-8")
    except OSError as exc:
        logger.warning("Не удалось записать CA-бандл %s: %s", COMBINED_BUNDLE, exc)
        fallback = RU_CA_DIR / "tmp_bundle.pem"
        try:
            fallback.write_text("\n".join(parts), encoding="utf-8")
            return str(fallback)
        except OSError:
            return certifi.where()

    logger.info("CA-бандл собран: %s (%s сертификатов Минцифры)", COMBINED_BUNDLE, len(ru_certs))
    return str(COMBINED_BUNDLE)


def create_ssl_context() -> ssl.SSLContext:
    """SSL-контекст с проверкой сертификата и доверием к Минцифры."""
    return ssl.create_default_context(cafile=build_ca_bundle())


def verify_option() -> str:
    """Значение для параметра ``verify`` в httpx (путь к PEM-бандлу)."""
    return build_ca_bundle()


def system_bundle_hint() -> str | None:
    """Подсказка для логов: есть ли сертификат Минцифры в системном бандле."""
    for path in SYSTEM_CA_BUNDLES:
        content = _read(path)
        if "Russian Trusted Root CA" in content:
            return str(path)
    return None

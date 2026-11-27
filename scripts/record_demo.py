"""Запись демо-видео стенда одним дублем: Playwright проходит сценарий docs/demo-script.md.

python scripts/record_demo.py [--url https://smart-search.containerapps.ru] [--out demo]
Субтитры и подсветка курсора добавляются поверх страницы во время записи; монтажа нет.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OVERLAY = """
(() => {
  const cap = document.createElement('div');
  cap.id = 'demo-caption';
  Object.assign(cap.style, {position: 'fixed', left: '50%', bottom: '64px', transform: 'translateX(-50%)', zIndex: 99999,
    maxWidth: '760px', padding: '12px 20px', borderRadius: '14px', background: 'rgba(10,16,40,.88)', color: '#fff',
    font: '600 19px/1.35 Onest, system-ui, sans-serif', textAlign: 'center', boxShadow: '0 10px 30px rgba(0,0,0,.35)',
    transition: 'opacity .25s', opacity: '0', pointerEvents: 'none'});
  document.body.appendChild(cap);
  const cur = document.createElement('div');
  cur.id = 'demo-cursor';
  Object.assign(cur.style, {position: 'fixed', left: '-40px', top: '-40px', width: '22px', height: '22px', marginLeft: '-11px',
    marginTop: '-11px', borderRadius: '50%', background: 'rgba(255,181,71,.55)', border: '2px solid #ffb547', zIndex: 99998,
    pointerEvents: 'none', transition: 'left .45s ease, top .45s ease, transform .15s'});
  document.body.appendChild(cur);
})();
"""


def ensure_overlay(page: Page) -> None:
    if not page.evaluate("!!document.getElementById('demo-caption')"):
        page.evaluate(OVERLAY)


def caption(page: Page, text: str) -> None:
    ensure_overlay(page)
    page.evaluate("""t => { const c = document.getElementById('demo-caption'); c.textContent = t; c.style.opacity = t ? '1' : '0'; }""", text)


def point(page: Page, selector: str, click: bool = True) -> None:
    """Плавно подводит видимый курсор к элементу и кликает."""
    ensure_overlay(page)
    el = page.locator(selector).first
    el.scroll_into_view_if_needed()
    box = el.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.evaluate("""([x, y]) => { const c = document.getElementById('demo-cursor'); c.style.left = x + 'px'; c.style.top = y + 'px'; }""", [x, y])
    time.sleep(0.6)
    if click:
        page.evaluate("() => { const c = document.getElementById('demo-cursor'); c.style.transform = 'scale(.7)'; setTimeout(() => c.style.transform = '', 160); }")
        page.mouse.click(x, y)


def search(page: Page, text: str, delay: int = 85, wait: float = 3.0) -> None:
    point(page, "#q")
    page.fill("#q", "")
    page.type("#q", text, delay=delay)
    time.sleep(0.4)
    page.keyboard.press("Enter")
    time.sleep(wait)


def run(url: str, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, record_video_dir=str(out),
                                  record_video_size={"width": 1440, "height": 900}, locale="ru-RU")
        page = ctx.new_page()
        t0 = time.time()
        page.goto(url)
        page.wait_for_selector("#status-line .dot", timeout=60000)
        time.sleep(1.0)
        caption(page, "Умный поиск для store.softline.ru. Каждая точка — продукт: 10 200 позиций в наличии, похожие лежат рядом")
        time.sleep(7)

        # Подсказки при вводе и транслитерация
        caption(page, "Подсказки появляются во время ввода — сразу с товарами")
        point(page, "#q")
        page.type("#q", "мдаем", delay=170)
        time.sleep(3.2)
        caption(page, "«мдаемон» по-русски — поиск понимает, что это MDaemon, и объясняет, почему товар в выдаче")
        page.type("#q", "он", delay=170)
        page.keyboard.press("Enter")
        time.sleep(5.5)

        # Раскладка, реестр, акция
        caption(page, "Запрос в английской раскладке: «fcnhf kbyerc» → Astra Linux. Метки реестра ПО, сертификатов и акции — из фида")
        search(page, "fcnhf kbyerc", wait=6.5)

        # Карточка и допродажа
        caption(page, "Карточка продукта работает на допродажу: что берут вместе с ОС — дуги на карте ведут в другие разделы")
        point(page, ".result >> nth=0")
        time.sleep(6.5)
        caption(page, "Совместимость с Dr.Web, Kaspersky и Кибер Бэкапом подтверждена документацией вендоров — ссылки на источники")
        page.locator(".sources").first.scroll_into_view_if_needed()
        time.sleep(6.5)
        point(page, "#drawer-close")
        time.sleep(1.0)

        # Намерение: оборудование или ПО
        caption(page, "«сервер» — это оборудование…")
        search(page, "сервер", wait=5.0)
        caption(page, "…а «по для сервера» — программы. Поиск различает намерение по контексту")
        search(page, "по для сервера", wait=5.5)

        # Нет в каталоге
        caption(page, "Если продукта нет в каталоге, поиск честно говорит об этом и предлагает решения той же задачи")
        search(page, "teamviewer", wait=6.5)

        # GigaChat
        caption(page, "Описание задачи своими словами уточняет GigaChat — выдача обновляется. Остальные запросы обходятся без модели")
        search(page, "программа для чертежей", wait=8.0)

        # Фильтры
        caption(page, "Фильтры как в магазине: российское ПО, производитель, сортировка по цене")
        search(page, "антивирь", wait=3.5)
        point(page, "button[data-f=domestic]")
        time.sleep(3.5)

        # Аналитика
        caption(page, "Команда магазина видит карту спроса: где ищут и где поиск не нашёл товар")
        point(page, "button[data-mode=analytics]")
        time.sleep(6.0)
        caption(page, "Запросы, понятые только с помощью GigaChat, добавляются в словарь одной кнопкой — дальше без модели")
        sug = page.locator(".add-syn:not([disabled])")
        if sug.count():
            sug.first.scroll_into_view_if_needed()
            time.sleep(1.2)
            point(page, ".add-syn:not([disabled])")
        else:
            page.locator(".sug").first.scroll_into_view_if_needed()
        time.sleep(5.0)
        caption(page, "Экономический эффект на цифрах из ТЗ: оценка, которую подтверждает A/B-тест после внедрения")
        page.locator("#calc").scroll_into_view_if_needed()
        time.sleep(7.0)
        caption(page, "Поиск, допродажа и аналитика — в одном продукте")
        point(page, "button[data-mode=search]")
        time.sleep(4.0)
        caption(page, "")
        print(f"длительность сценария: {time.time() - t0:.1f} с")
        video = page.video.path()
        ctx.close()
        browser.close()
    return Path(video)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://smart-search.containerapps.ru")
    ap.add_argument("--out", type=Path, default=Path("demo"))
    args = ap.parse_args()
    webm = run(args.url, args.out)
    mp4 = args.out / "demo.mp4"
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
    shutil.copy2(webm, args.out / "demo.webm")
    print("видео:", mp4.resolve())


if __name__ == "__main__":
    main()

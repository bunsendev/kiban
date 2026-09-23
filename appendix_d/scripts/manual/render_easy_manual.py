from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-not-found]

SCENES = (
    (
        "01_start.png",
        "1",
        "かんたん予測を開く",
        "起動後に表示されたURLを開きます。最初に、このPCを接続します。",
        8.0,
    ),
    (
        "02_connect.png",
        "2",
        "接続コードを入力",
        "セットアップ時に渡された接続コードを入力し、「接続する」を押します。",
        7.0,
    ),
    (
        "03_choose_file.png",
        "3",
        "CSVまたはZIPを選ぶ",
        "「ここを押してファイルを選択」を押し、予測に使うデータを選びます。",
        10.0,
    ),
    (
        "04_selected.png",
        "4",
        "選択したデータを確認",
        "ファイル名と容量を確認します。違う場合は「選び直す」を押します。",
        8.0,
    ),
    (
        "05_analyze.png",
        "5",
        "分析を開始",
        "準備できました、と表示されたら「データを分析する」を押します。",
        10.0,
    ),
    (
        "06_waiting.png",
        "6",
        "受付後はそのまま待つ",
        "受付番号と処理中の表示を確認します。画面は閉じず、同じボタンを繰り返し押しません。",
        7.0,
    ),
    (
        "07_result.png",
        "7",
        "最初に色と見出しを確認",
        "緑は次へ進めます。黄は一部確認、赤は修正してやり直す状態です。",
        10.0,
    ),
    (
        "08_metrics.png",
        "8",
        "3つの件数を確認",
        "確認件数、利用できる件数、確認が必要な件数を左から順に読みます。",
        9.0,
    ),
    (
        "09_reading.png",
        "9",
        "確認事項と次の操作",
        "確認事項がなければ次へ進めます。この結果はデータ形式の確認で、予測値や精度ではありません。",
        10.0,
    ),
)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    family = "YuGothB.ttc" if bold else "YuGothR.ttc"
    candidates = (
        Path("C:/Windows/Fonts") / family,
        Path("C:/Windows/Fonts/meiryob.ttc" if bold else "C:/Windows/Fonts/meiryo.ttc"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def fit_text(draw: ImageDraw.ImageDraw, text: str, maximum: int, size: int, bold=False):
    current = size
    while current > 18:
        selected = font(current, bold)
        if draw.textbbox((0, 0), text, font=selected)[2] <= maximum:
            return selected
        current -= 1
    return font(18, bold)


def title_frame() -> Image.Image:
    image = Image.new("RGB", (1280, 720), "#0f2743")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((92, 86, 1188, 634), radius=26, fill="#ffffff")
    draw.text((142, 142), "YOSOKU KIBAN", font=font(24, True), fill="#1f65d6")
    draw.text(
        (142, 220),
        "ファイルアップロードから\n分析結果の読み方まで",
        font=font(54, True),
        fill="#10243f",
        spacing=18,
    )
    draw.text((142, 405), "担当者向け かんたん操作マニュアル", font=font(28), fill="#52657a")
    draw.rounded_rectangle((142, 500, 628, 564), radius=16, fill="#eaf2ff")
    draw.text(
        (170, 515),
        "所要時間：約1分30秒  ｜  操作：9ステップ",
        font=font(22, True),
        fill="#174f9e",
    )
    return image


def ending_frame() -> Image.Image:
    image = Image.new("RGB", (1280, 720), "#f2f6fb")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (120, 96, 1160, 624),
        radius=28,
        fill="#ffffff",
        outline="#d4deea",
        width=2,
    )
    draw.ellipse((554, 145, 726, 317), fill="#e6f7ee")
    draw.text((602, 171), "✓", font=font(78, True), fill="#21875a")
    draw.text((362, 350), "色・件数・確認事項を見れば完了です", font=font(34, True), fill="#10243f")
    draw.text(
        (302, 430),
        "黄は内容を確認します。赤やエラーの場合は、受付番号と表示内容を管理担当者へ連絡してください。",
        font=font(21),
        fill="#52657a",
    )
    draw.text(
        (430, 515),
        "この結果はデータ形式の確認です。予測値・予測精度は次の工程で確認します",
        font=font(22, True),
        fill="#174f9e",
    )
    return image


def caption_frame(source: Path, step: str, title: str, detail: str) -> Image.Image:
    screen = Image.open(source).convert("RGB").resize((1280, 720))
    overlay = Image.new("RGBA", screen.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, 520, 1280, 720), fill=(12, 34, 59, 236))
    draw.rounded_rectangle((54, 548, 124, 618), radius=20, fill="#ffad14")
    step_font = font(32, True)
    bbox = draw.textbbox((0, 0), step, font=step_font)
    draw.text((89 - (bbox[2] - bbox[0]) / 2, 559), step, font=step_font, fill="#10243f")
    draw.text((154, 548), title, font=fit_text(draw, title, 1050, 32, True), fill="#ffffff")
    draw.text((154, 602), detail, font=fit_text(draw, detail, 1050, 23), fill="#dbe7f4")
    return Image.alpha_composite(screen.convert("RGBA"), overlay).convert("RGB")


def iter_video_frames(frames_dir: Path, fps: int):
    opening = title_frame()
    for _ in range(int(8.0 * fps)):
        yield opening
    for filename, step, title, detail, duration in SCENES:
        scene = caption_frame(frames_dir / filename, step, title, detail)
        for _ in range(int(duration * fps)):
            yield scene
    ending = ending_frame()
    for _ in range(int(7.0 * fps)):
        yield ending


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fps", type=int, default=24)
    args = parser.parse_args()
    from imageio_ffmpeg import write_frames

    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = write_frames(
        str(args.output),
        (1280, 720),
        fps=args.fps,
        codec="libx264",
        pix_fmt_in="rgb24",
        pix_fmt_out="yuv420p",
        output_params=["-movflags", "+faststart", "-crf", "22"],
    )
    writer.send(None)
    try:
        for frame in iter_video_frames(args.frames_dir, args.fps):
            writer.send(frame.tobytes())
    finally:
        writer.close()


if __name__ == "__main__":
    main()

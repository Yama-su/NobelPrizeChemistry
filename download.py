#!/usr/bin/env python3
"""
全ノーベル化学賞の「受賞核心論文」を CSV から抽出して Sci-Hub から網羅的にダウンロード

Windows(CP932環境)でのUnicodeエンコードエラーとゼロ除算エラーへの対策済。
アップロードされた 'Chemistry publication record.csv' を読み込み、
'Is prize-winning paper' == 'YES' の論文（核心論文）を対象にダウンロードを行います。
"""

import os
import sys
import json
import time
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging
from datetime import datetime

# ==========================================
# 設定
# ==========================================
SAVE_DIR = "Nobel_Papers_Complete"
DATA_FILE_CSV = "Chemistry publication record.csv"  # 入力CSVファイル
STATS_FILE = "download_statistics.json"

# Sci-Hub ミラーリスト
SCI_HUB_MIRRORS = [
    "https://sci-hub.jp/",
    "https://sci-hub.se/",
    "https://sci-hub.st/",
    "https://sci-hub.ru/",
    "https://sci-hub.tw/",
    "https://sci-hub.hkvisa.net/",
    "https://sci-hub.mkdnsfr.eu/",
    "https://sci-hub.scihubtw.tw/",
]

# ==========================================
# ロギング設定
# ==========================================
file_handler = logging.FileHandler('nobel_download.log', encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ==========================================
# ユーティリティ関数
# ==========================================
def sanitize_filename(filename):
    """ファイル名から危険な文字を削除"""
    return "".join(c for c in filename if c.isalnum() or c in "._- ")

def safe_request(url, timeout=15, retries=3):
    """安全なリクエスト（リトライ機能付き）"""
    for attempt in range(retries):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=timeout)
            return response
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"タイムアウト。{wait_time}秒待機後にリトライ...")
                time.sleep(wait_time)
            continue
        except Exception as e:
            logger.error(f"リクエスト失敗: {e}")
            return None
    return None

# ==========================================
# Sci-Hub ダウンロード関数
# ==========================================
def download_from_scihub(doi, save_path, max_retries=5):
    """
    複数のSci-Hubミラーから論文をダウンロード
    """
    if os.path.exists(save_path):
        logger.info(f"[SKIP] すでに存在するためスキップ: {save_path}")
        return True
    
    for mirror_idx, mirror_url in enumerate(SCI_HUB_MIRRORS):
        for attempt in range(max_retries):
            try:
                search_url = f"{mirror_url}{doi}"
                logger.debug(f"  [{mirror_idx+1}/{len(SCI_HUB_MIRRORS)}] {mirror_url} を試行...")
                
                response = safe_request(search_url, timeout=20)
                if response is None or response.status_code != 200:
                    logger.debug(f"    → HTTP {response.status_code if response else 'None'}")
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                pdf_url = None
                
                # PDF URL を抽出 (iframe, object, embed, onclick から探索)
                iframe = soup.find('iframe')
                if iframe and iframe.get('src'):
                    pdf_url = iframe['src']
                    logger.debug("    → iframe から URL を抽出")
                
                if not pdf_url:
                    obj = soup.find('object', type='application/pdf')
                    if obj and obj.get('data'):
                        pdf_url = obj['data']
                        logger.debug("    → object から URL を抽出")
                
                if not pdf_url:
                    embed = soup.find('embed', type='application/pdf')
                    if embed and embed.get('src'):
                        pdf_url = embed['src']
                        logger.debug("    → embed から URL を抽出")
                
                if not pdf_url:
                    buttons = soup.find_all('button', onclick=True)
                    for btn in buttons:
                        onclick = btn.get('onclick', '')
                        if 'location.href' in onclick:
                            match = re.search(r"'(https?:[^']+)'", onclick)
                            if match:
                                pdf_url = match.group(1)
                                logger.debug("    → ボタン onclick から URL を抽出")
                                break
                
                if not pdf_url:
                    logger.debug("    → PDF URL が見つかりません")
                    continue
                
                # URL を正規化
                if pdf_url.startswith('//'):
                    pdf_url = 'https:' + pdf_url
                elif not pdf_url.startswith('http'):
                    pdf_url = urljoin(mirror_url, pdf_url)
                
                # PDF をダウンロード
                logger.debug(f"    → PDF をダウンロード中: {pdf_url[:60]}...")
                pdf_response = safe_request(pdf_url, timeout=30)
                
                if pdf_response is None:
                    logger.debug("    → PDF ダウンロード失敗")
                    continue
                
                # PDF の妥当性を検証
                if not pdf_response.content.startswith(b'%PDF'):
                    logger.debug(f"    → 無効なPDF（ファイルサイズ: {len(pdf_response.content)} bytes）")
                    if pdf_response.content.startswith(b'<!DOCTYPE'):
                        logger.debug("    → HTMLが返ってきています")
                        continue
                
                # ファイルを保存
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'wb') as f:
                    f.write(pdf_response.content)
                
                logger.info(f"  [SUCCESS] ダウンロード成功 [{mirror_idx+1}/{len(SCI_HUB_MIRRORS)}]: {save_path}")
                return True
            
            except Exception as e:
                logger.debug(f"    → エラー: {str(e)[:60]}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                continue
        
        time.sleep(1)
    
    logger.warning(f"  [FAILED] 全ミラーからのダウンロード失敗: {doi}")
    return False

# ==========================================
# メイン処理
# ==========================================
def download_all_papers():
    """
    CSVから受賞核心論文を抽出し、すべてダウンロード
    """
    os.makedirs(SAVE_DIR, exist_ok=True)
    
    # データファイルの存在確認
    if not os.path.exists(DATA_FILE_CSV):
        logger.error(f"データファイルが見つかりません: {DATA_FILE_CSV}")
        return None

    # CSVデータを読み込む
    logger.info(f"データファイルを読み込み中: {DATA_FILE_CSV}")
    try:
        df_all = pd.read_csv(DATA_FILE_CSV)
    except Exception as e:
        logger.error(f"CSVの読み込みに失敗しました: {e}")
        return None
    
    # 受賞の決定打となった核心論文（Is prize-winning paper == YES）のみを抽出
    df_prize = df_all[df_all["Is prize-winning paper"].astype(str).str.upper() == "YES"].copy()
    
    # 処理しやすいように辞書のリスト形式に変換
    nobel_data = df_prize.to_dict(orient="records")
    
    logger.info("=" * 70)
    logger.info("ノーベル化学賞 受賞核心論文 一括ダウンロード開始")
    logger.info(f"対象（核心論文）: {len(nobel_data)}件")
    logger.info("=" * 70)
    
    # 統計情報初期化
    stats = {
        "start_time": datetime.now().isoformat(),
        "total": len(nobel_data),
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "no_doi": 0,
        "by_year": {},
        "by_century": {
            "20th": {"success": 0, "failed": 0},
            "21st": {"success": 0, "failed": 0},
        },
        "failed_papers": [],
    }
    
    failed_list = []
    success_count = 0
    failed_count = 0
    skip_count = 0
    
    for idx, record in enumerate(nobel_data, 1):
        # カラム名に合わせたマッピング
        year = int(record.get('Prize year', 0))
        title = record.get('Title', 'Unknown')
        names = record.get('Laureate name', 'Unknown')
        doi = str(record.get('DOI', '')).strip()
        
        progress = f"[{idx:3d}/{len(nobel_data)}]"
        
        # DOI が欠損している（NaN含む）、または空の場合
        if not doi or doi == 'nan' or doi == '':
            logger.info(f"{progress} [SKIP] スキップ ({year}年): DOIが未登録の古い文献です")
            skip_count += 1
            stats["no_doi"] += 1
            continue
        
        logger.info(f"{progress} [{year}年] {names} - {title[:50]}...")
        
        # ファイル名を生成（[受賞年]_[受賞者名]_[タイトル短縮].pdf）
        safe_name = sanitize_filename(names.split(',')[0])  # 苗字のみを抽出してシンプルに
        safe_title = sanitize_filename(title)[:40]
        filename = f"{SAVE_DIR}/[{year:04d}]_{safe_name}_{safe_title}.pdf"
        
        # ダウンロード実行
        success = download_from_scihub(doi, filename)
        
        if success:
            success_count += 1
            stats["success"] += 1
        else:
            failed_count += 1
            stats["failed"] += 1
            failed_list.append({
                'year': year,
                'title': title,
                'names': names,
                'doi': doi,
            })
            stats["failed_papers"].append({
                'year': year,
                'title': title,
                'doi': doi,
                'url': f"https://doi.org/{doi}"
            })
        
        # 年代別統計
        if str(year) not in stats["by_year"]:
            stats["by_year"][str(year)] = {"success": 0, "failed": 0}
        
        if success:
            stats["by_year"][str(year)]["success"] += 1
        else:
            stats["by_year"][str(year)]["failed"] += 1
        
        # 世紀別統計
        century = "20th" if year < 2000 else "21st"
        if success:
            stats["by_century"][century]["success"] += 1
        else:
            stats["by_century"][century]["failed"] += 1
        
        # サーバー負荷軽減のためのスリープ
        time.sleep(1)
    
    # 統計情報を更新
    stats["end_time"] = datetime.now().isoformat()
    stats["skipped"] = skip_count
    
    # 結果サマリー表示
    logger.info("\n" + "=" * 70)
    logger.info("[STATS] ダウンロード完了")
    logger.info("=" * 70)
    logger.info(f"成功: {success_count}件")
    logger.info(f"失敗: {failed_count}件")
    logger.info(f"スキップ: {skip_count}件 (DOIなし)")
    
    effective_total = len(nobel_data) - skip_count
    if effective_total > 0:
        success_rate = (success_count / effective_total) * 100
        logger.info(f"成功率: {success_rate:.1f}%")
    else:
        logger.info("成功率: 0.0% (有効なDOIを持つ論文がありませんでした)")
    logger.info("=" * 70)
    
    # 世紀別統計
    logger.info("\n[STATS] 世紀別統計")
    for century in ["20th", "21st"]:
        s = stats["by_century"][century]["success"]
        f = stats["by_century"][century]["failed"]
        total = s + f
        if total > 0:
            rate = s / total * 100
            logger.info(f"  {century}: {s}/{total} ({rate:.1f}%)")
    
    # 失敗リストの HTML 生成
    if failed_list:
        generate_failed_list_html(failed_list, stats["failed_papers"])
    
    # 統計をJSONで保存
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    logger.info(f"\n[SUCCESS] 統計情報を保存: {STATS_FILE}")
    
    # ダウンロード確認
    downloaded_files = [f for f in os.listdir(SAVE_DIR) if f.endswith('.pdf')]
    logger.info(f"[SUCCESS] ローカルに保存されたPDF: {len(downloaded_files)}件")
    
    return stats

def generate_failed_list_html(failed_list, failed_papers):
    """
    ダウンロード失敗リストを HTML で生成
    """
    html_path = f"{SAVE_DIR}/failed_papers.html"
    
    html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Failed Papers - ノーベル化学賞論文ダウンロード失敗リスト</title>
    <style>
        body {
            font-family: sans-serif;
            padding: 30px;
            background: #f5f5f5;
        }
        h1 { color: #333; }
        .paper {
            background: white;
            padding: 15px;
            margin-bottom: 15px;
            border-left: 4px solid #e74c3c;
            border-radius: 3px;
        }
        .year { color: #3498db; font-weight: bold; font-size: 1.1em; }
        .title { margin: 10px 0; font-size: 1.05em; }
        .doi { color: #666; font-family: monospace; font-size: 0.9em; }
        a { color: #3498db; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .count { background: #3498db; color: white; padding: 5px 10px; border-radius: 3px; }
    </style>
</head>
<body>
<h1>❌ ダウンロード失敗リスト</h1>
<p>以下の<span class="count">"""
    
    html_content += f"{len(failed_list)}</span>件の論文は自動ダウンロードに失敗しました。</p>\n"
    html_content += "<p>以下のリンクから手動でダウンロードしてください。</p>\n\n"
    
    for item in failed_papers:
        html_content += f"""<div class="paper">
    <div class="year">[{item['year']}年] {item['title']}</div>
    <div class="doi">DOI: {item['doi']}</div>
    <a href="{item['url']}" target="_blank">→ CrossRef で論文を探す</a> | 
    <a href="https://sci-hub.se/{item['doi']}" target="_blank">→ Sci-Hub で再度試行</a>
</div>
"""
    
    html_content += """
</body>
</html>
"""
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    logger.info(f"[SUCCESS] 失敗リストを生成: {html_path}")

if __name__ == "__main__":
    stats = download_all_papers()
    
    logger.info("\n[SUCCESS] 全処理完了!")
    logger.info(f"保存先: {SAVE_DIR}/")
    logger.info(f"統計: {STATS_FILE}")
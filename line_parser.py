import sqlite3
import json
import os
import sys
from datetime import datetime

COCOA_OFFSET = 978307200

def find_database_file(target_path):
    """ファイルまたはフォルダからDBファイルを特定する"""
    if os.path.isfile(target_path):
        return target_path
    
    if os.path.isdir(target_path):
        print(f"フォルダ内を検索中: {target_path}")
        for root, dirs, files in os.walk(target_path):
            for file in files:
                if file.lower() in ['line.sqlite', 'talk.sqlite', 'naver_line']:
                    found = os.path.join(root, file)
                    print(f"-> データベース発見: {found}")
                    return found
    return None

def parse_line_db(db_path):
    actual_db_path = find_database_file(db_path)
    
    if not actual_db_path or not os.path.exists(actual_db_path):
        print(f"エラー: 有効なLINEデータベース (Line.sqlite / Talk.sqlite) がフォルダ内に見つかりませんでした。")
        return None

    conn = sqlite3.connect(actual_db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    is_ios = 'ZMESSAGE' in tables
    is_android = 'chat_history' in tables

    if not (is_ios or is_android):
        print("エラー: 読み込んだファイルはLINEのデータベースではありません。")
        conn.close()
        return None

    user_map = {}
    chat_map = {}
    chats_data = {}

    if is_ios:
        print("[検出] iOS版データベース (Line.sqlite)")
        if 'ZUSER' in tables:
            try:
                cursor.execute("SELECT ZMID, COALESCE(ZCUSTOMNAME, ZNAME) FROM ZUSER")
                for mid, name in cursor.fetchall():
                    if mid and name: user_map[str(mid)] = name
            except Exception: pass

        if 'ZCHAT' in tables:
            try:
                cursor.execute("SELECT Z_PK, ZNAME FROM ZCHAT")
                for pk, name in cursor.fetchall():
                    if pk and name: chat_map[str(pk)] = name
            except Exception: pass

        query = """
            SELECT ZCHAT, ZTEXT, ZISFROMME, ZSENDER, ZCREATEDTIME, ZCONTENTTYPE
            FROM ZMESSAGE
            WHERE ZCHAT IS NOT NULL
            ORDER BY ZCREATEDTIME ASC
        """
        cursor.execute(query)
        for chat_id, text, is_me, sender_id, raw_time, msg_type in cursor.fetchall():
            chat_key = str(chat_id)
            if chat_key not in chats_data:
                chats_data[chat_key] = {
                    "id": chat_key,
                    "name": chat_map.get(chat_key, f"トークルーム ({chat_key})"),
                    "messages": []
                }

            ts = (raw_time + COCOA_OFFSET) if raw_time else 0
            dt_str = datetime.fromtimestamp(ts).strftime('%Y/%m/%d %H:%M') if ts > 0 else ''

            is_me_bool = bool(is_me)
            sender_name = "自分" if is_me_bool else user_map.get(str(sender_id), chats_data[chat_key]["name"])
            content = text if text else get_media_label(msg_type)

            chats_data[chat_key]["messages"].append({
                "text": content,
                "isMe": is_me_bool,
                "sender": sender_name,
                "time": dt_str
            })

    elif is_android:
        print("[検出] Android版データベース (Talk.sqlite)")
        if 'contacts' in tables:
            try:
                cursor.execute("SELECT m_id, COALESCE(custom_name, name) FROM contacts")
                for mid, name in cursor.fetchall():
                    if mid and name: user_map[str(mid)] = name
            except Exception: pass

        query = """
            SELECT chat_id, content, from_mid, created_time, type
            FROM chat_history
            WHERE chat_id IS NOT NULL
            ORDER BY created_time ASC
        """
        cursor.execute(query)
        for chat_id, text, sender_id, raw_time, msg_type in cursor.fetchall():
            chat_key = str(chat_id)
            if chat_key not in chats_data:
                chats_data[chat_key] = {
                    "id": chat_key,
                    "name": user_map.get(chat_key, f"トークルーム ({chat_key})"),
                    "messages": []
                }

            ts = raw_time / 1000.0 if raw_time and raw_time > 10000000000 else raw_time
            dt_str = datetime.fromtimestamp(ts).strftime('%Y/%m/%d %H:%M') if ts else ''

            is_me_bool = not sender_id or sender_id == '0'
            sender_name = "自分" if is_me_bool else user_map.get(str(sender_id), "相手")
            content = text if text else get_media_label(msg_type)

            chats_data[chat_key]["messages"].append({
                "text": content,
                "isMe": is_me_bool,
                "sender": sender_name,
                "time": dt_str
            })

    conn.close()
    return list(chats_data.values())

def get_media_label(msg_type):
    labels = {
        1: "[📷 画像]", 2: "[🎥 動画]", 3: "[🎙 音声]",
        7: "[📍 位置情報]", 11: "[🎨 スタンプ]", 12: "[🎴 連絡先]",
        14: "[📞 通話履歴]", 15: "[📎 ファイル]"
    }
    return labels.get(msg_type, "[メディア]")

def generate_html_viewer(parsed_data, output_file="index.html"):
    json_bytes = json.dumps(parsed_data, ensure_ascii=False)
    
    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>LINE Talk Viewer</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, sans-serif; display: flex; height: 100vh; background: #f0f2f5; }}
        #sidebar {{ width: 320px; background: white; border-right: 1px solid #ddd; display: flex; flex-direction: column; }}
        .search-box {{ padding: 10px; border-bottom: 1px solid #eee; }}
        .search-box input {{ width: 100%; padding: 8px; border-radius: 16px; border: 1px solid #ccc; }}
        #chat-list {{ flex: 1; overflow-y: auto; }}
        .chat-item {{ padding: 12px; border-bottom: 1px solid #f0f0f0; cursor: pointer; }}
        .chat-item:hover {{ background: #f8f9fa; }}
        .chat-item.active {{ background: #e6f9e6; font-weight: bold; }}
        #chat-view {{ flex: 1; background: #8cabd9; display: flex; flex-direction: column; }}
        .chat-header {{ background: white; padding: 15px; border-bottom: 1px solid #ddd; font-weight: bold; }}
        #msg-container {{ flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 10px; }}
        .msg-row {{ display: flex; flex-direction: column; max-width: 70%; }}
        .msg-row.me {{ align-self: flex-end; align-items: flex-end; }}
        .msg-row.other {{ align-self: flex-start; align-items: flex-start; }}
        .meta {{ font-size: 11px; color: rgba(255,255,255,0.9); margin-bottom: 2px; text-shadow: 0 1px 2px rgba(0,0,0,0.3); }}
        .bubble {{ padding: 9px 13px; border-radius: 14px; background: white; font-size: 14px; line-height: 1.4; word-break: break-word; white-space: pre-wrap; }}
        .me .bubble {{ background: #85e249; }}
    </style>
</head>
<body>
    <div id="sidebar">
        <div class="search-box">
            <input type="text" placeholder="検索..." oninput="filterList(this.value)">
        </div>
        <div id="chat-list"></div>
    </div>
    <div id="chat-view">
        <div class="chat-header" id="chat-title">トークルームを選択してください</div>
        <div id="msg-container"></div>
    </div>

    <script>
        const chatData = {json_bytes};

        function renderList(list) {{
            const container = document.getElementById('chat-list');
            container.innerHTML = '';
            list.forEach((c) => {{
                const div = document.createElement('div');
                div.className = 'chat-item';
                div.innerText = `${{c.name}} (${{c.messages.length}}件)`;
                div.onclick = () => selectChat(c, div);
                container.appendChild(div);
            }});
        }}

        function selectChat(chat, el) {{
            document.querySelectorAll('.chat-item').forEach(i => i.classList.remove('active'));
            if(el) el.classList.add('active');
            document.getElementById('chat-title').innerText = `${{chat.name}} (全${{chat.messages.length}}件)`;
            
            const container = document.getElementById('msg-container');
            container.innerHTML = '';
            chat.messages.forEach(m => {{
                const row = document.createElement('div');
                row.className = `msg-row ${{m.isMe ? 'me' : 'other'}}`;
                row.innerHTML = `<div class="meta">${{escapeHtml(m.sender)}} • ${{m.time}}</div><div class="bubble">${{escapeHtml(m.text)}}</div>`;
                container.appendChild(row);
            }});
            container.scrollTop = container.scrollHeight;
        }}

        function filterList(q) {{
            const filtered = chatData.filter(c => c.name.toLowerCase().includes(q.toLowerCase()));
            renderList(filtered);
        }}

        function escapeHtml(str) {{
            return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }}

        renderList(chatData);
    </script>
</body>
</html>"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[成功] 閲覧用ファイルを出力しました: {os.path.abspath(output_file)}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python line_parser.py <フォルダまたはDBファイルのパス>")
        sys.exit(1)

    target_path = sys.argv[1]
    data = parse_line_db(target_path)
    if data:
        generate_html_viewer(data)

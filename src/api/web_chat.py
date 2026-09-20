"""Web-based chat UI + JSON API backed by the shared chat_service dispatcher."""
from __future__ import annotations

import os

from flask import Blueprint, jsonify, render_template_string, request

from chat_service import ChatRequest, dispatch
from reporting.line_report_renderer import LineReportRenderer
from reporting.web_chat_renderer import render_brief_html, render_report_html

web_chat_bp = Blueprint('web_chat', __name__)

_PAGE = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SM Stock AI Agent</title>
<style>
  :root { --bg:#f3f4f6; --card:#ffffff; --accent:#16803c; --user:#111827; --muted:#6b7280; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:'Sarabun','Noto Sans Thai',system-ui,sans-serif; background:var(--bg); }
  #app { max-width:760px; margin:0 auto; height:100dvh; display:flex; flex-direction:column; }
  header { padding:14px 20px; background:var(--card); border-bottom:1px solid #e5e7eb;
           font-weight:700; color:var(--user); }
  header small { display:block; color:var(--muted); font-weight:400; }
  #chat { flex:1; overflow-y:auto; padding:18px; display:flex; flex-direction:column; gap:12px; }
  .msg { max-width:85%; padding:10px 14px; border-radius:14px; font-size:14px; line-height:1.55;
         white-space:pre-wrap; word-break:break-word; }
  .user { align-self:flex-end; background:var(--user); color:#fff; border-bottom-right-radius:4px; }
  .bot  { align-self:flex-start; background:var(--card); border:1px solid #e5e7eb;
          border-bottom-left-radius:4px; }
  .bot.card { padding:0; overflow:hidden; max-width:92%; }
  .card h3 { margin:0; padding:12px 16px 4px; font-size:16px; }
  .card .body { padding:0 16px 14px; }
  .card img.chart { width:100%; border-radius:8px; margin:6px 0; }
  .badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:700; }
  .badge.Positive { background:#e8f5e9; color:#16803c; }
  .badge.Mixed    { background:#fff8e1; color:#8a6100; }
  .badge.Negative { background:#ffebee; color:#b42318; }
  .card ul { margin:6px 0; padding-left:18px; }
  .card li { font-size:13px; color:#333; }
  .disclaimer { font-size:11px; color:#9ca3af; padding:8px 16px; border-top:1px solid #f3f4f6; }
  form { display:flex; gap:8px; padding:12px; background:var(--card); border-top:1px solid #e5e7eb; }
  input { flex:1; padding:11px 14px; border:1px solid #d1d5db; border-radius:10px; font-size:14px; }
  button { padding:11px 18px; background:var(--accent); color:#fff; border:0; border-radius:10px;
           font-size:14px; cursor:pointer; }
  button:disabled { opacity:.5; }
  .typing { color:var(--muted); font-size:13px; align-self:flex-start; padding:4px 14px; }
</style>
</head>
<body>
<div id="app">
  <header>📈 SM Stock AI Agent<small>Web Chat — add / news / report / watchlist / help</small></header>
  <div id="chat"></div>
  <form id="f">
    <input id="i" autocomplete="off" placeholder="เช่น: news PTT หรือ add NVDA หรือ report KTB">
    <button>ส่ง</button>
  </form>
</div>
<script>
const chat = document.getElementById('chat');
const form = document.getElementById('f');
const input = document.getElementById('i');
const uid = 'web-' + (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2));

function bubble(cls, html) {
  const div = document.createElement('div');
  div.className = 'msg ' + cls;
  if (html) div.innerHTML = html; else div.textContent = '';
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function renderCard(p) {
  const div = bubble('bot card', p.html);
  return div;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  bubble('user', null).textContent = text;
  input.value = '';
  const typing = bubble('bot typing', null); typing.textContent = 'กำลังประมวลผล…';
  try {
    const res = await fetch('/web/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, user_id: uid}),
    });
    const data = await res.json();
    typing.remove();
    for (const msg of data.messages || []) {
      if (msg.kind === 'text') bubble('bot', null).textContent = msg.text;
      else if (msg.kind === 'market_brief') renderCard(msg);
      else if (msg.kind === 'report_card') renderCard(msg);
      else bubble('bot', null).textContent = JSON.stringify(msg.payload);
    }
  } catch (err) {
    typing.remove();
    bubble('bot', null).textContent = '! เชื่อมต่อเซิร์ฟเวอร์ไม่สำเร็จ';
  }
});
bubble('bot', null).textContent =
  'สวัสดีครับ 👋 ลองพิมพ์ "help" เพื่อดูคำสั่ง หรือ "news PTT" เพื่อดู Market Brief';
</script>
</body>
</html>"""


@web_chat_bp.route('/web/chat', methods=['GET'])
def chat_page():
    return render_template_string(_PAGE)


@web_chat_bp.route('/web/api/chat', methods=['POST'])
def chat_api():
    data = request.get_json(silent=True) or {}
    text = str(data.get('text') or '').strip()
    user_id = str(data.get('user_id') or 'anonymous')[:64]

    req = ChatRequest(channel='web', channel_user_id=user_id, text=text)
    responses = dispatch(req)

    messages = []
    for resp in responses:
        if resp.kind == 'market_brief':
            messages.append({
                'kind': 'market_brief',
                'html': render_brief_html(resp.payload['symbol'], resp.payload['brief']),
            })
        elif resp.kind == 'report_card':
            messages.append({
                'kind': 'report_card',
                'html': render_report_html(resp.payload),
            })
        else:
            messages.append({'kind': 'text', 'text': resp.text})
    return jsonify({'messages': messages})

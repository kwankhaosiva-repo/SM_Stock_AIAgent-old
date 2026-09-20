"""Discord bot adapter backed by the shared chat_service dispatcher.

Run standalone:  python -m src.discord_bot   (or python src/discord_bot.py)
Requires DISCORD_BOT_TOKEN in the environment. Messages with image/file
attachments are not needed; all output is text + embeds.
"""
from __future__ import annotations

import os

IMPACT_EMOJI = {'Positive': '🟢', 'Mixed': '🟡', 'Negative': '🔴'}
OUTLOOK_EMOJI = {'Positive': '🟢', 'Neutral': '🟡', 'Cautious': '🔴'}


def build_embeds(responses):
    """Convert ChatResponse list into discord embed-ready dicts."""
    import discord  # local import so tests can run without discord.py

    embeds = []
    for resp in responses:
        if resp.kind == 'market_brief':
            brief = resp.payload.get('brief', {})
            symbol = resp.payload.get('symbol', '')
            impact = str(brief.get('impact', 'Mixed'))
            emoji = IMPACT_EMOJI.get(impact, '🟡')
            color = {
                'Positive': discord.Color.green(),
                'Negative': discord.Color.red(),
            }.get(impact, discord.Color.gold())

            embed = discord.Embed(
                title=f'📰 Market Brief — {symbol} {emoji} {impact}',
                description=str(brief.get('summary') or '')[:4000],
                color=color,
            )
            news = [f'• {n}' for n in (brief.get('news') or [])[:5]]
            if news:
                embed.add_field(name='🗞 ข่าวย้ายตลาด', value='\n'.join(news)[:1024], inline=False)
            advice = [f'{i}. {a}' for i, a in enumerate((brief.get('advice') or [])[:4], 1)]
            if advice:
                embed.add_field(name='💡 คำแนะนำ', value='\n'.join(advice)[:1024], inline=False)
            provider = str(brief.get('provider') or 'ai')
            label = 'โหมดสำรอง (ตัวเลขล้วน)' if provider == 'fallback' else f'AI: {provider}'
            embed.set_footer(text=f'{brief.get("disclaimer", "")} ({label})')
            embeds.append(embed)

        elif resp.kind == 'report_card':
            report = resp.payload or {}
            symbol = str(report.get('symbol', '')).upper()
            outlook = report.get('signal') or 'Neutral'
            emoji = OUTLOOK_EMOJI.get(outlook, '🟡')
            color = {
                'Positive': discord.Color.green(),
                'Cautious': discord.Color.red(),
            }.get(outlook, discord.Color.gold())

            advice = report.get('advice') or {}
            metrics = report.get('metrics') or {}
            price = metrics.get('price')
            price_str = f'{float(price):,.2f}' if price else '-'
            reasons = [f'{i}. {r}' for i, r in enumerate((advice.get('reasons') or [])[:3], 1)]
            risks = advice.get('risks') or []

            embed = discord.Embed(
                title=f'📊 {symbol} {emoji} {outlook} — {price_str}',
                description=str(report.get('reason') or '')[:4000],
                color=color,
            )
            if reasons:
                embed.add_field(name='📌 เหตุผลเชิงประจักษ์', value='\n'.join(reasons)[:1024], inline=False)
            if risks:
                embed.add_field(name='⚠️ ความเสี่ยง', value='\n'.join(f'• {r}' for r in risks[:2])[:1024], inline=False)
            history = report.get('history') or []
            if len(history) >= 2:
                from analysis.chart_service import ChartService
                url = ChartService.generate_sparkline_url(history, trend=outlook)
                if url:
                    embed.set_image(url=url)
            embed.set_footer(text='ข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน')
            embeds.append(embed)

        else:
            embeds.append(None)  # plain text
    return embeds


def main():
    import discord
    from chat_service import ChatRequest, dispatch

    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        raise SystemExit('DISCORD_BOT_TOKEN is not set')

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f'[Discord] Logged in as {client.user} (id={client.user.id})')

    @client.event
    async def on_message(message):
        if message.author.bot:
            return
        req = ChatRequest(
            channel='discord',
            channel_user_id=str(message.author.id),
            text=message.content,
            display_name=message.author.display_name,
        )
        responses = dispatch(req)
        for resp, embed in zip(responses, build_embeds(responses) + [None] * len(responses)):
            if embed is not None:
                await message.reply(embed=embed)
            else:
                await message.reply(resp.text[:2000] or '…')

    client.run(token)


if __name__ == '__main__':
    main()

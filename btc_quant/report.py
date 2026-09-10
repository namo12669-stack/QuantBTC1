from __future__ import annotations
from .common import VERSION,utc

def format_plan(plan:dict,model:dict|None=None,paper=False,demo=False)->str:
    label='DEMO - SYNTHETIC, NOT LIVE' if demo else 'PAPER ONLY - UNVALIDATED' if paper else 'HISTORICAL-GATE-QUALIFIED PLAN'
    x=plan;sig=x['signal'];lines=[f'BTC QUANT BOT 2 v{VERSION}',label,
        'BINANCE USD-M | BTCUSDT PERPETUAL | CLOSED 1H',f"{x['action']} | {x['strategy']['id']}",
        f"Companion: {x['strategy']['peer'] or 'BTC-only'} (context, not a hedge order)",'',
        f"ENTRY LIMIT: {x['entry_price']:,.2f}",f"STOP LOSS: {x['stop_loss']:,.2f}",f"TAKE PROFIT: {x['take_profit']:,.2f}",
        f"Quantity: {x['quantity_btc']:.6f} BTC | Notional: {x['notional_usdt']:.2f} USDT",
        f"Leverage: {x['leverage']}x ISOLATED | Initial margin ~{x['initial_margin_usdt']:.2f} USDT",
        f"Equity input: {x['equity_used_usdt']:.2f} USDT (manual, not account read)",
        f"Planned loss incl. reserves: {x['planned_loss_usdt']:.2f} USDT",
        f"Planned profit after reserves: {x['planned_profit_usdt']:.2f} USDT",
        f"Net reward/risk: {x['net_reward_risk']:.2f} | User hard risk ceiling: 50 USDT",'',
        'Activate ONLY at '+utc(x['activate_at']).tz_convert('Asia/Bangkok').strftime('%Y-%m-%d %H:%M +07'),
        'Cancel unfilled at '+utc(x['entry_expires_at']).tz_convert('Asia/Bangkok').strftime('%Y-%m-%d %H:%M +07'),
        f"Time exit: {x['hold_hours']}h after fill hour; no later than "+utc(x['latest_time_exit']).tz_convert('Asia/Bangkok').strftime('%m-%d %H:%M +07'),
        'Cancel if SL or TP is breached before entry. Do not chase or place early.', '', 'WHY THIS PLAN:']
    for k,v in list(sig['details'].items())[:7]:
        if isinstance(v,float):v=f'{v:.5g}'
        lines.append(f'- {k}: {v}')
    if model and model.get('evidence'):
        ev=model['evidence']['subsets'].get(x['side'],{});wr=ev.get('win_rate')
        if wr is not None:lines+=['',f"Frozen holdout {x['side']}: {ev['n']} trades, observed wins {wr:.1%}",
            f"Historical lower bound: {ev['historical_lower_bound']:.1%}",
            f"Gate for this direction: {'PASSED' if x['side'] in model.get('approved_sides',[]) else 'NOT PASSED'}"]
    lines+=['','Next-trade probability: NOT ESTIMATED. Loss can exceed the planned amount.',
        'Liquidation price: NOT account-verified. Check Binance Mark Price/liquidation before entry.',
        'SL uses Last/Contract Price in the simulation. Place exchange-side STOP MARKET + TP after fill.',
        'No orders placed. Bot does not know your actual fill, open position or balance. No news verification.',f"Plan ID: {x['id']}"]
    return '\n'.join(lines)


def status_text(status:str,details:str='')->str:
    return f'BTC QUANT BOT 2 v{VERSION}\n{status}\n{details}\nNo entry order was placed. No next-trade probability is asserted.'

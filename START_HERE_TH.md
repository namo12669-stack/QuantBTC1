# BTC Quant Bot 2 v1.1 - คู่มือเริ่มต้น

เวอร์ชันนี้แก้ปัญหา `HTTP 451` ที่คุณเจอใน **Bot2 - Check Data** โดยเลิกใช้ Binance USD-M เป็น data provider ทั้งใน Backtest และ Live scan แล้วเปลี่ยนเป็น **Coinbase Exchange public spot data** เพื่อไม่ให้ Backtest ใช้ตลาดหนึ่งแต่ Live ใช้อีกตลาดหนึ่ง

ไม่มี Proxy/VPN/วิธี bypass และไม่มีการส่งคำสั่งซื้อขายจริง

## 1. อัปโหลด v1.1 ทับ repository Bot 2 เดิม

แตก ZIP แล้วอัปโหลดไฟล์ด้านในทับของเดิม โดยต้องเห็น:

```text
.github/
  workflows/
    bot2_setup.yml
    bot2_check_data.yml
    bot2_research.yml
    bot2_scan.yml
    tests.yml
btc_quant/
config.yaml
main.py
README.md
```

Secrets เดิมใช้ต่อได้:

```text
TELEGRAM_BOT2_TOKEN
TELEGRAM_BOT2_CHAT_ID
```

ไม่ต้องสร้าง Telegram bot ใหม่อีกครั้ง

## 2. เช็ก Version

เปิด `config.yaml` ต้องเห็น:

```yaml
version: 1.1.0
venue: coinbase_exchange_spot
bitcoin: BTC-USD
```

ถ้ายังเห็น `binance_usdm` หรือ `BTCUSDT` แปลว่ายังอัปโหลดไฟล์เก่าไม่หมด

## 3. รัน Check Data ใหม่

ไปที่:

**Actions -> Bot2 - Check Data -> Run workflow**

รอบนี้ Log ควรเป็นชื่อคู่ประมาณ:

```text
BTC-USD {'status': 'OK', ...}
ETH-USD {'status': 'OK', ...}
SOL-USD {'status': 'OK', ...}
LINK-USD {'status': 'OK', ...}
ADA-USD {'status': 'OK', ...}
LTC-USD {'status': 'OK', ...}
```

ถ้า GitHub runner ยังเข้า Coinbase ไม่ได้ ระบบจะหยุดและเขียนเหตุผลลง `provider_check.json` โดยไม่สลับไป provider อื่นเงียบ ๆ

## 4. รัน Research Backtest

เมื่อ Check Data ผ่าน:

**Actions -> Bot2 - Research Backtest -> Run workflow**

ครั้งแรกอาจใช้เวลาหลายนาที เพราะข้อมูล 1H ถูกโหลดแบบแบ่งช่วงตามข้อจำกัดจำนวน candle ต่อ request ของ Coinbase หลังจากนั้น GitHub cache สามารถนำชุดข้อมูลที่ผ่าน SHA256 validation กลับมาใช้ได้เมื่อ config ยังเหมือนเดิม

ดูผลจาก `BACKTEST_REPORT.md` และไฟล์:

```text
pair_selection.csv
btc_only_baselines.csv
holdout_trades.csv
holdout_equity.csv
model.json
```

ระบบจะเลือก Candidate จาก Validation ก่อน แล้วค่อยเปิด Holdout ของ Candidate เดียว ไม่เลือกตัวใหม่เพราะเห็นผล Holdout สวยกว่า

## 5. เกณฑ์ 80%

ตามที่คุณปรับจาก 90% เป็น 80% ตอนนี้ Strict gate ใช้:

```yaml
minimum_win_rate_lower_bound: 0.80
```

แต่ความหมายคือ **ขอบล่างเชิงสถิติของ Historical net win rate ต้องมากกว่า 80%** ไม่ใช่ข้อความว่า “เทรดถัดไปมีโอกาสชนะ 80%”

ระบบยังตรวจอย่างอื่นร่วมด้วย เช่นจำนวนเทรดขั้นต่ำ BUY/SELL แยกฝั่ง Profit Factor ผลหลัง Cost stress ความสม่ำเสมอรายเดือน และ Drawdown

ถ้าไม่ผ่าน จะขึ้นประมาณ:

```text
NO_VALIDATED_80_PERCENT_EDGE
```

อันนี้ไม่ใช่ Error แต่หมายถึงข้อมูลยังไม่รองรับการอ้าง Edge ระดับที่ตั้งไว้

## 6. Pair ใน v1.1 เปลี่ยนอย่างไร

v1.0 จำลอง Pair trade สองขาและต้องใช้ Funding ของ Perpetual แต่เมื่อเราเปลี่ยนมาใช้ Spot จะไม่สมเหตุผลที่จะสร้าง Short companion/funding ปลอม ๆ

ดังนั้น v1.1 ใช้ ETH/SOL/LINK/ADA/LTC เป็น **ข้อมูลประกอบเพื่อสร้างสัญญาณ BTC** เช่น Pair spread หรือ Lead-lag แต่ผล Backtest เป็น BTC direction เดียว:

```text
BTC: BUY / LONG
Context: ETH-USD
```

หรือ

```text
BTC: SELL / SHORT
Context: SOL-USD
```

คำว่า SELL/SHORT ยังเป็นทิศทางวิจัย ไม่ได้หมายความว่า Coinbase Spot ของคุณสามารถ Short ได้ และบอตไม่ได้ส่ง Order

## 7. ทดสอบ Telegram

ไปที่ **Bot2 - Hourly Signals** แล้วเริ่มด้วย:

```text
mode: demo
```

จากนั้นลอง:

```text
mode: status
```

หลัง Research สำเร็จ สามารถลอง:

```text
mode: paper
```

Paper จะใช้ข้อมูลตลาดจริงและ Candidate ที่ Research เลือก แต่ไม่ต้องผ่าน strict 80% gate ส่วน Schedule อัตโนมัติใช้ `strict` และจะไม่ฝืนแจ้ง BUY/SELL ถ้าหลักฐานไม่ผ่าน

## 8. ถ้ายัง Error

ส่ง Screenshot ของ **Bot2 - Check Data** หรือข้อความใน `provider_check.json` มาได้ โดยเฉพาะบรรทัด `BTC-USD` และ `ETH-USD` จะบอกได้ว่าปัญหาคือ Network, HTTP status, schema หรือ candle ขาด

อย่าส่ง Telegram Bot Token ใน Screenshot หรือแชท

// Zerodha's brokerage calculator, worked again here so that zerodha.py can be checked against it to the paisa.
// Rates and rounding steps are the ones its page used when read on 11 Nov 2026, for NSE equity intraday, NSE
// equity delivery and MCX non-agricultural futures (gold, crude oil). Each sum keeps the page's order of
// multiplying and adding: in floating point the order can move the last bit, and now and then a rounded paisa.
// Input on stdin: a JSON list of {f: "intra" | "delivery" | "mcx", bp, sp, qty, mult}. Output: the charges.

const paise = x => Number(x.toFixed(2));        // two decimals, rounded the page's way
const rupees = x => Math.round(paise(x));       // STT and stamp duty are whole rupees

function total(brokerage, tax, exchange, gst, sebi, stamp) {
  return {brokerage, tax, exchange, sebi, stamp, gst, total: paise(brokerage + tax + exchange + gst + sebi + stamp)};
}

function equity(bp, sp, qty, intraday) {
  const turnover = paise((bp + sp) * qty);
  const perOrder = value => (value * 0.0003 > 20 ? 20 : paise(value * 0.0003));  // 0.03%, at most Rs 20 an order
  const brokerage = intraday ? paise(perOrder(bp * qty) + perOrder(sp * qty)) : 0;
  const stt = intraday ? rupees(sp * qty * 0.00025) : rupees(turnover * 0.001);     // 0.025% of sales; 0.1% of both
  const sebi = paise(turnover * 0.000001);                                           // Rs 10 a crore
  const exchange = paise(paise(0.0000297 * turnover) + paise(0.000001 * turnover));   // NSE 0.00297%, IPFT Rs 10 a crore
  const gst = paise(0.18 * (brokerage + exchange + sebi));
  const stamp = rupees(bp * qty * (intraday ? 0.00003 : 0.00015));                   // on the buy side
  return total(brokerage, stt, exchange, gst, sebi, stamp);
}

function mcx(bp, sp, qty, lot) {
  const turnover = paise((bp + sp) * lot * qty);
  const perOrder = price => {
    const value = price * lot * qty;
    return value > 200000 ? 20 : (value * 0.0003 > 20 ? 20 : paise(value * 0.0003));
  };
  const brokerage = perOrder(bp) + perOrder(sp);                // added without rounding again
  const ctt = paise(0.0001 * sp * qty * lot);                   // 0.01% of sales, in paise
  const sebi = paise(turnover * 0.000001);
  const exchange = paise(0.000021 * turnover);                  // MCX 0.0021%
  const gst = paise(0.18 * (brokerage + exchange + sebi));
  const stamp = rupees(bp * qty * lot * 0.00002);               // 0.002% of the buy
  return total(brokerage, ctt, exchange, gst, sebi, stamp);
}

const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(cases.map(c => c.f === "intra" ? equity(c.bp, c.sp, c.qty, true)
  : c.f === "delivery" ? equity(c.bp, c.sp, c.qty, false) : mcx(c.bp, c.sp, c.qty, c.mult))));

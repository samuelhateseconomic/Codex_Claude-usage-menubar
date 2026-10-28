export function formatTokens(value) {
  if (value === null || value === undefined) return 'Not recorded';
  const n = BigInt(value);
  if (n < 1_000_000n) return n.toLocaleString('en-US');
  let divisor = n >= 1_000_000_000n ? 1_000_000_000n : 1_000_000n;
  let scaled = (n * 100n + divisor / 2n) / divisor;
  if (divisor === 1_000_000n && scaled >= 100_000n) {divisor = 1_000_000_000n;scaled = (n * 100n + divisor / 2n) / divisor;}
  const fraction = (scaled % 100n).toString().padStart(2,'0').replace(/0+$/,'');
  return `${scaled / 100n}${fraction ? '.' + fraction : ''}${divisor === 1_000_000n ? 'M' : 'B'}`;
}
export function chartScale(maximum){
  if(!(maximum>0))return 5;
  const target=maximum/5;
  const power=10**Math.floor(Math.log10(target));
  const step=[1,2,5,10].map(n=>n*power).find(n=>n>=target) || 10*power;
  return step*5;
}

// Fixed-point display only: half-even rounding from the exact USD wire string.
// API validation owns bounds; reject malformed/oversized input here rather than
// coercing null or binary floating-point numbers to money. Bounded exponent
// strings remain compatible with Decimal's legacy fee serialization.
function fixedMoney(value,digits,integerDigits,fractionDigits=12){
  if(!Number.isInteger(digits)||digits<0||digits>12)throw new RangeError('USD display precision must be 0–12');
  const match=typeof value==='string'&&value.match(new RegExp(`^(-?)(\\d{1,26})(?:\\.(\\d{1,${fractionDigits}}))?(?:[eE]([+-]?\\d{1,2}))?$`));
  if(!match)return 'Unavailable';
  const [,negative,integer,decimal='',exponent='0']=match;
  const text=integer+decimal,point=integer.length+Number(exponent); // bounded position, not the USD amount
  const whole=(point>0?text.slice(0,point).padEnd(point,'0'):'0').replace(/^0+(?=\d)/,'');
  const fraction=(point<0?'0'.repeat(-point)+text:text.slice(Math.max(0,point))).replace(/0+$/,'');
  if(whole.length>integerDigits||fraction.length>fractionDigits)return 'Unavailable';
  const scale=10n**BigInt(digits);
  let units=BigInt(whole)*scale+BigInt(fraction.slice(0,digits).padEnd(digits,'0')||'0');
  const discarded=fraction.slice(digits);
  if(discarded){
    const remainder=BigInt(discarded),half=5n*10n**BigInt(discarded.length-1);
    if(remainder>half||(remainder===half&&units%2n===1n))units++;
  }
  const grouped=(units/scale).toString().replace(/\B(?=(\d{3})+(?!\d))/g,',');
  const displayedFraction=digits?'.'+(units%scale).toString().padStart(digits,'0'):'';
  return `${negative&&units!==0n?'-':''}${grouped}${displayedFraction}`;
}

export const formatMoney=(value,digits=3,integerDigits=24)=>fixedMoney(value,digits,integerDigits);
// Contributions/rounding adjustments carry up to 18 places, unlike the
// 12-place event totals. Round their wire strings for display only.
export function formatUsd(value){
  const formatted=fixedMoney(value,2,24,18);
  if(formatted==='Unavailable')return formatted;
  const nonzero=/[1-9]/.test(value.split(/[eE]/)[0]);
  return formatted==='0.00'&&nonzero?(value.startsWith('-')?'−<0.01':'<0.01'):formatted;
}

export const formatCredits=(value,digits=2)=>formatMoney(value,digits,26);
export function formatEstimate(value,digits=2,credits=false){
  const formatted=credits?formatCredits(value,digits):formatMoney(value,digits);
  if(formatted==='Unavailable')return formatted;
  return /^[0,.]+$/.test(formatted)&&/[1-9]/.test(value)?'<'+(digits?'0.'+'0'.repeat(digits-1)+'1':'1'):formatted;
}

export function formatDifference(value,digits=3){
  const formatted=formatMoney(value,digits);
  if(formatted==='Unavailable')return 'comparison unavailable';
  // Preserve the exact difference's sign even if display rounding reaches zero.
  const negative=value.startsWith('-')&&/[1-9]/.test(value.split(/[eE]/)[0]);
  return (negative?'−$':'+$')+(formatted.startsWith('-')?formatted.slice(1):formatted);
}

// A fractional token average is a display value; canonical counts stay integers.
export function formatAverageTokens(value){
  if(typeof value!=='string'||!/^\d+(?:\.\d{1,18})?$/.test(value))return 'Unavailable';
  const whole=BigInt(value.split('.')[0]);
  const exponent=whole>=1_000_000_000n?9:whole>=1_000_000n?6:0;
  const shown=fixedMoney(value+(exponent?'e-'+exponent:''),2,24,30);
  return shown+(exponent===9?'B':exponent===6?'M':'');
}

export function formatAverageCredits(value){
  const shown=fixedMoney(value,2,26,18);
  return shown==='0.00'&&/[1-9]/.test(value)?'<0.01':shown;
}

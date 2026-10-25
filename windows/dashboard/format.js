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
export function formatMoney(value, digits=3){
  if(!Number.isInteger(digits)||digits<0||digits>12)throw new RangeError('USD display precision must be 0–12');
  const match=typeof value==='string'&&value.match(/^(-?)(\d{1,24})(?:\.(\d{1,12}))?(?:[eE]([+-]?\d{1,2}))?$/);
  if(!match)return 'Unavailable';
  const [,negative,integer,decimal='',exponent='0']=match;
  const text=integer+decimal,point=integer.length+Number(exponent); // bounded position, not the USD amount
  const whole=(point>0?text.slice(0,point).padEnd(point,'0'):'0').replace(/^0+(?=\d)/,'');
  const fraction=(point<0?'0'.repeat(-point)+text:text.slice(Math.max(0,point))).replace(/0+$/,'');
  if(whole.length>24||fraction.length>12)return 'Unavailable';
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

export function formatDifference(value,digits=3){
  const formatted=formatMoney(value,digits);
  if(formatted==='Unavailable')return 'comparison unavailable';
  // Preserve the exact difference's sign even if display rounding reaches zero.
  const negative=value.startsWith('-')&&/[1-9]/.test(value.split(/[eE]/)[0]);
  return (negative?'−$':'+$')+(formatted.startsWith('-')?formatted.slice(1):formatted);
}

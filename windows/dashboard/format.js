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

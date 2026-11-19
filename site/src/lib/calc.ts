/** Level monthly payment on a fully amortising loan. */
export function monthlyPayment(principal: number, annualRatePct: number, months: number): number {
  if (!(principal > 0) || !(months > 0)) return 0;
  const r = annualRatePct / 100 / 12;
  if (r === 0) return principal / months;
  return (principal * r) / (1 - Math.pow(1 + r, -months));
}

export function totalInterest(principal: number, annualRatePct: number, months: number): number {
  return monthlyPayment(principal, annualRatePct, months) * months - principal;
}

/** Debt service coverage ratio: cash available for debt service / annual debt service. */
export function dscr(annualCashFlow: number, principal: number, annualRatePct: number, months: number): number | null {
  const annualDebt = monthlyPayment(principal, annualRatePct, months) * 12;
  if (!(annualDebt > 0)) return null;
  return annualCashFlow / annualDebt;
}

/** Remaining balance after k payments. */
export function balanceAfter(principal: number, annualRatePct: number, months: number, k: number): number {
  const r = annualRatePct / 100 / 12;
  if (k >= months) return 0;
  if (r === 0) return principal * (1 - k / months);
  const p = monthlyPayment(principal, annualRatePct, months);
  return principal * Math.pow(1 + r, k) - (p * (Math.pow(1 + r, k) - 1)) / r;
}

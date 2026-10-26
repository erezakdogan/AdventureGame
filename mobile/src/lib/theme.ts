import type { Rating } from './types';

export const colors = {
  bg: '#0B0F17',
  surface: '#121826',
  surfaceAlt: '#1A2233',
  border: '#263047',
  text: '#E6EAF2',
  muted: '#8A94A8',
  faint: '#5B6578',
  accent: '#7C9CFF',
  accentText: '#0B0F17',
  up: '#2BD98A',
  down: '#FF5C6C',
  warn: '#FFB547',
  info: '#5CC8FF',
};

export const radius = { sm: 8, md: 12, lg: 16 };
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 };

export const ratingColor: Record<Rating, string> = {
  Buy: '#2BD98A',
  Overweight: '#8BE3B5',
  Hold: '#FFB547',
  Underweight: '#FF9A7A',
  Sell: '#FF5C6C',
  REVIEW: '#8A94A8',
};

export const pnlColor = (v: number | null | undefined) =>
  v == null || Math.abs(v) < 1e-9 ? colors.muted : v > 0 ? colors.up : colors.down;

/**
 * YS Rent A Car - Theme & Design Tokens
 * Glassmorphism + Sportive Red-Black
 */
/**
 * BORDO/BURGUNDY TEMA — premium kiralama deneyimi için
 * primary: #800020 — klasik bordo
 * primaryLight: #A02040 — vurgu/parıltı
 * primaryDark: #5C0011 — gölgeler
 */
export const Colors = {
  bg: {
    base: '#0A0608',
    surface: '#15090C',
    surface2: '#1F0F13',
    elevated: '#291319',
    glass: 'rgba(255, 255, 255, 0.05)',
    glassDark: 'rgba(0, 0, 0, 0.4)',
    glassRed: 'rgba(128, 0, 32, 0.14)',
  },
  brand: {
    primary: '#800020',
    primaryDark: '#5C0011',
    primaryLight: '#A02040',
    primaryGlow: 'rgba(128, 0, 32, 0.45)',
    accent: '#B8003A',
    // Bordo gradient renkler (animasyonlu efekt için)
    gradientStart: '#5C0011',
    gradientMid: '#800020',
    gradientEnd: '#A02040',
  },
  text: {
    primary: '#FFFFFF',
    secondary: '#B8A0A6',
    tertiary: '#7A6266',
    disabled: '#443838',
  },
  status: {
    musait: '#34C759',
    dolu: '#B8003A',
    bakim: '#FF9500',
    success: '#34C759',
    warning: '#FF9500',
    error: '#B8003A',
    info: '#5AC8FA',
  },
  border: {
    base: 'rgba(255, 255, 255, 0.08)',
    light: 'rgba(255, 255, 255, 0.04)',
    accent: 'rgba(160, 32, 64, 0.45)',
  },
};

export const Spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
};

export const Radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  pill: 9999,
};

export const Typography = {
  h1: { fontSize: 32, fontWeight: '800' as const, letterSpacing: -0.5 },
  h2: { fontSize: 26, fontWeight: '800' as const, letterSpacing: -0.3 },
  h3: { fontSize: 20, fontWeight: '700' as const },
  h4: { fontSize: 17, fontWeight: '700' as const },
  body: { fontSize: 15, fontWeight: '400' as const },
  bodyBold: { fontSize: 15, fontWeight: '600' as const },
  caption: { fontSize: 13, fontWeight: '400' as const },
  micro: { fontSize: 11, fontWeight: '600' as const, letterSpacing: 0.5 },
};

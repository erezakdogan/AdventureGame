import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';

import { colors, radius, ratingColor, space } from '../lib/theme';
import type { Rating } from '../lib/types';

export function Screen({
  children,
  refreshing,
  onRefresh,
  scroll = true,
  style,
}: {
  children: ReactNode;
  refreshing?: boolean;
  onRefresh?: () => void;
  scroll?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  if (!scroll) return <View style={[styles.screen, styles.screenPad, style]}>{children}</View>;
  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[styles.screenPad, style]}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefresh ? (
          <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={colors.muted} />
        ) : undefined
      }
    >
      {children}
    </ScrollView>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function H1({ children, style }: { children: ReactNode; style?: StyleProp<TextStyle> }) {
  return <Text style={[styles.h1, style]}>{children}</Text>;
}

export function H2({ children, style }: { children: ReactNode; style?: StyleProp<TextStyle> }) {
  return <Text style={[styles.h2, style]}>{children}</Text>;
}

export function Label({ children, style }: { children: ReactNode; style?: StyleProp<TextStyle> }) {
  return <Text style={[styles.label, style]}>{children}</Text>;
}

export function Body({
  children,
  style,
  muted,
  numberOfLines,
}: {
  children: ReactNode;
  style?: StyleProp<TextStyle>;
  muted?: boolean;
  numberOfLines?: number;
}) {
  return (
    <Text numberOfLines={numberOfLines} style={[styles.body, muted && { color: colors.muted }, style]}>
      {children}
    </Text>
  );
}

export function Row({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.row, style]}>{children}</View>;
}

export function KV({ k, v, color }: { k: string; v: ReactNode; color?: string }) {
  return (
    <View style={styles.kv}>
      <Text style={styles.kvKey}>{k}</Text>
      {typeof v === 'string' || typeof v === 'number' ? (
        <Text style={[styles.kvVal, color ? { color } : null]}>{v}</Text>
      ) : (
        v
      )}
    </View>
  );
}

export function Button({
  title,
  onPress,
  kind = 'primary',
  disabled,
  loading,
  small,
  style,
}: {
  title: string;
  onPress: () => void;
  kind?: 'primary' | 'secondary' | 'danger' | 'buy' | 'sell' | 'ghost';
  disabled?: boolean;
  loading?: boolean;
  small?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const bg = {
    primary: colors.accent,
    secondary: colors.surfaceAlt,
    danger: '#3A1820',
    buy: colors.up,
    sell: colors.down,
    ghost: 'transparent',
  }[kind];
  const fg = {
    primary: colors.accentText,
    secondary: colors.text,
    danger: colors.down,
    buy: '#06281A',
    sell: '#2D070C',
    ghost: colors.accent,
  }[kind];
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.button,
        small && styles.buttonSmall,
        { backgroundColor: bg, opacity: disabled ? 0.45 : pressed ? 0.8 : 1 },
        kind === 'secondary' && { borderWidth: 1, borderColor: colors.border },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <Text style={[styles.buttonText, small && { fontSize: 13 }, { color: fg }]}>{title}</Text>
      )}
    </Pressable>
  );
}

export function Field({
  label,
  hint,
  style,
  ...props
}: TextInputProps & { label?: string; hint?: string; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[{ marginBottom: space.md }, style]}>
      {label ? <Label style={{ marginBottom: 6 }}>{label}</Label> : null}
      <TextInput
        placeholderTextColor={colors.faint}
        autoCorrect={false}
        {...props}
        style={styles.input}
      />
      {hint ? <Text style={styles.hint}>{hint}</Text> : null}
    </View>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  style,
}: {
  options: { label: string; value: T }[];
  value: T;
  onChange: (v: T) => void;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View style={[styles.segmented, style]}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <Pressable
            key={o.value}
            onPress={() => onChange(o.value)}
            style={[styles.segment, active && { backgroundColor: colors.accent }]}
          >
            <Text style={[styles.segmentText, active && { color: colors.accentText }]} numberOfLines={1}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Chips({
  options,
  selected,
  onToggle,
}: {
  options: { label: string; value: string }[];
  selected: string[];
  onToggle: (v: string) => void;
}) {
  return (
    <View style={styles.chips}>
      {options.map((o) => {
        const on = selected.includes(o.value);
        return (
          <Pressable
            key={o.value}
            onPress={() => onToggle(o.value)}
            style={[styles.chip, on && { backgroundColor: colors.accent, borderColor: colors.accent }]}
          >
            <Text style={[styles.chipText, on && { color: colors.accentText }]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Toggle({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <View style={styles.toggle}>
      <View style={{ flex: 1, paddingRight: space.md }}>
        <Body>{label}</Body>
        {hint ? <Text style={styles.hint}>{hint}</Text> : null}
      </View>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ true: colors.accent, false: colors.border }}
        thumbColor={colors.text}
      />
    </View>
  );
}

export function Stepper({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  format,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  format?: (v: number) => string;
}) {
  const clamp = (v: number) => Math.min(max, Math.max(min, Math.round(v / step) * step));
  return (
    <View style={styles.toggle}>
      <Body style={{ flex: 1 }}>{label}</Body>
      <Row style={{ gap: space.sm }}>
        <Button title="−" small kind="secondary" onPress={() => onChange(clamp(value - step))} disabled={value <= min} />
        <Text style={[styles.body, { minWidth: 56, textAlign: 'center' }]}>{format ? format(value) : value}</Text>
        <Button title="+" small kind="secondary" onPress={() => onChange(clamp(value + step))} disabled={value >= max} />
      </Row>
    </View>
  );
}

export function RatingBadge({ rating, large }: { rating: Rating | null | undefined; large?: boolean }) {
  if (!rating) return null;
  const c = ratingColor[rating] ?? colors.muted;
  return (
    <View style={[styles.badge, { borderColor: c, backgroundColor: `${c}22` }, large && styles.badgeLarge]}>
      <Text style={[styles.badgeText, { color: c }, large && { fontSize: 20 }]}>{rating}</Text>
    </View>
  );
}

export function Pill({ text, color = colors.muted }: { text: string; color?: string }) {
  return (
    <View style={[styles.pill, { borderColor: `${color}66`, backgroundColor: `${color}1A` }]}>
      <Text style={[styles.pillText, { color }]}>{text}</Text>
    </View>
  );
}

export function ErrorBanner({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <View style={styles.error}>
      <Text style={{ color: colors.down }}>{message}</Text>
    </View>
  );
}

export function Notice({ children, color = colors.info }: { children: ReactNode; color?: string }) {
  return (
    <View style={[styles.error, { borderColor: `${color}55`, backgroundColor: `${color}12` }]}>
      <Text style={{ color: colors.text, lineHeight: 20 }}>{children}</Text>
    </View>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <View style={{ alignItems: 'center', paddingVertical: space.xl }}>
      <Text style={[styles.h2, { textAlign: 'center' }]}>{title}</Text>
      {children ? <Body muted style={{ textAlign: 'center', marginTop: space.sm }}>{children}</Body> : null}
    </View>
  );
}

export function Loading() {
  return (
    <View style={{ paddingVertical: 40 }}>
      <ActivityIndicator color={colors.muted} />
    </View>
  );
}

export function Divider() {
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: colors.border, marginVertical: space.sm }} />;
}

export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  screenPad: { padding: space.lg, paddingBottom: 48, gap: space.md },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: space.lg,
  },
  h1: { color: colors.text, fontSize: 28, fontWeight: '700' },
  h2: { color: colors.text, fontSize: 17, fontWeight: '700' },
  label: { color: colors.muted, fontSize: 12, fontWeight: '600', letterSpacing: 0.6, textTransform: 'uppercase' },
  body: { color: colors.text, fontSize: 15, lineHeight: 21 },
  row: { flexDirection: 'row', alignItems: 'center' },
  kv: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 6, gap: space.md },
  kvKey: { color: colors.muted, fontSize: 14 },
  kvVal: { color: colors.text, fontSize: 14, fontWeight: '600', flexShrink: 1, textAlign: 'right' },
  button: {
    borderRadius: radius.md,
    paddingVertical: 13,
    paddingHorizontal: space.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonSmall: { paddingVertical: 7, paddingHorizontal: space.md, borderRadius: radius.sm },
  buttonText: { fontSize: 15, fontWeight: '700' },
  input: {
    backgroundColor: colors.surfaceAlt,
    color: colors.text,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: space.md,
    paddingVertical: 11,
    fontSize: 16,
  },
  hint: { color: colors.faint, fontSize: 12, marginTop: 4, lineHeight: 17 },
  segmented: {
    flexDirection: 'row',
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.md,
    padding: 3,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  segment: { flex: 1, paddingVertical: 8, alignItems: 'center', borderRadius: radius.sm },
  segmentText: { color: colors.muted, fontWeight: '600', fontSize: 13 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 7,
    backgroundColor: colors.surfaceAlt,
  },
  chipText: { color: colors.text, fontSize: 13, fontWeight: '600' },
  toggle: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8 },
  badge: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3, alignSelf: 'flex-start' },
  badgeLarge: { paddingHorizontal: 16, paddingVertical: 6 },
  badgeText: { fontWeight: '800', fontSize: 13 },
  pill: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2, alignSelf: 'flex-start' },
  pillText: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.4 },
  error: {
    borderWidth: 1,
    borderColor: `${colors.down}55`,
    backgroundColor: `${colors.down}12`,
    borderRadius: radius.md,
    padding: space.md,
  },
});

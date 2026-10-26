import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { pct, price } from '../lib/format';
import { colors, space } from '../lib/theme';
import type { Prediction, PredictionStats } from '../lib/types';
import { Body, Card, Label, Pill, Row } from './ui';

export function accuracyColor(v: number | null | undefined): string {
  if (v == null) return colors.muted;
  if (v >= 70) return colors.up;
  if (v >= 40) return colors.warn;
  return colors.down;
}

/** A 0-100% bar; values outside the range are pinned to the ends. */
export function ProgressBar({ value, color }: { value: number | null | undefined; color?: string }) {
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <View style={{ height: 6, backgroundColor: colors.surfaceAlt, borderRadius: 3, overflow: 'hidden' }}>
      <View style={{ height: 6, width: `${v}%`, backgroundColor: color ?? accuracyColor(value), borderRadius: 3 }} />
    </View>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <View style={{ width: '50%', paddingVertical: 6, paddingRight: space.sm }}>
      <Text style={{ color: colors.muted, fontSize: 12 }}>{label}</Text>
      <Text style={{ color: colors.text, fontSize: 17, fontWeight: '700' }}>{value}</Text>
      {hint ? <Text style={{ color: colors.faint, fontSize: 11 }}>{hint}</Text> : null}
    </View>
  );
}

const rate = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(0)}%`);

export function AccuracyCard({
  stats,
  title = 'Forecast accuracy',
  link,
}: {
  stats: Partial<PredictionStats> | null | undefined;
  title?: string;
  link?: { label: string; href: string };
}) {
  const [explain, setExplain] = useState(false);
  if (!stats) return null;
  const acc = stats.avg_accuracy_pct ?? null;
  return (
    <Card>
      <Row style={{ justifyContent: 'space-between' }}>
        <Label>{title}</Label>
        <Pressable onPress={() => setExplain((x) => !x)}>
          <Text style={{ color: colors.accent, fontSize: 13 }}>{explain ? 'Hide' : 'How is this measured?'}</Text>
        </Pressable>
      </Row>
      <Row style={{ alignItems: 'flex-end', gap: space.md, marginTop: space.sm }}>
        <Text style={{ color: accuracyColor(acc), fontSize: 40, fontWeight: '800' }}>{acc == null ? '—' : `${acc.toFixed(0)}%`}</Text>
        <Body muted style={{ marginBottom: 8, flex: 1 }}>
          average accuracy over {stats.scored ?? 0} scored forecast{stats.scored === 1 ? '' : 's'}
          {stats.open ? ` · ${stats.open} still open` : ''}
        </Body>
      </Row>
      <ProgressBar value={acc} />
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: space.md }}>
        <Metric label="Direction right" value={rate(stats.direction_rate_pct)} />
        <Metric label="Target hit in time" value={rate(stats.target_hit_rate_pct)} />
        <Metric label="Precision" value={rate(stats.avg_precision_pct)} hint="closeness to the target" />
        <Metric label="Best reach" value={rate(stats.avg_peak_reach_pct)} hint="furthest move toward target" />
        {stats.avg_return_pct != null ? (
          <Metric label="Avg move in its favor" value={pct(stats.avg_return_pct)} />
        ) : null}
        {stats.stop_hit_rate_pct != null ? <Metric label="Stopped out" value={rate(stats.stop_hit_rate_pct)} /> : null}
      </View>
      {explain && (
        <View style={{ marginTop: space.sm, gap: 6 }}>
          <Body style={{ fontSize: 13 }}>
            Every time the bot buys (or sells expecting a drop) it states a target price and a deadline. When the
            deadline passes, the real price path is checked:
          </Body>
          <Body muted style={{ fontSize: 13 }}>
            • Accuracy: how far the price got toward the target by the deadline. Bought at 1.00 expecting 1.20; at the
            deadline it is 1.12, so 60%. Wrong-way moves score 0, reaching or passing the target scores 100.
          </Body>
          <Body muted style={{ fontSize: 13 }}>
            • Precision: how close the deadline price landed to the target. Overshooting counts against it too: 1.12
            and 1.28 both score 60%, because the size of the move was misjudged either way.
          </Body>
          <Body muted style={{ fontSize: 13 }}>
            • Target hit in time: the target traded at any point before the deadline, even if the price fell back.
          </Body>
          <Body muted style={{ fontSize: 13 }}>
            • Direction right: the price at least moved the predicted way. A Hold counts as right if the price stayed
            in a small band.
          </Body>
        </View>
      )}
      {link ? (
        <Pressable onPress={() => router.push(link.href as never)} style={{ marginTop: space.md }}>
          <Text style={{ color: colors.accent, fontWeight: '700' }}>{link.label} ›</Text>
        </Pressable>
      ) : null}
    </Card>
  );
}

function timeLeft(hours: number): string {
  if (hours <= 0) return 'awaiting score';
  if (hours < 1) return `${Math.round(hours * 60)}m left`;
  if (hours < 48) return `${hours.toFixed(1)}h left`;
  return `${Math.round(hours / 24)}d left`;
}

export function PredictionRow({ p }: { p: Prediction }) {
  const arrow = p.direction === 'up' ? '▲' : p.direction === 'down' ? '▼' : '◆';
  const dirColor = p.direction === 'up' ? colors.up : p.direction === 'down' ? colors.down : colors.warn;
  const open = p.status === 'open';
  const progress = open ? p.current_progress_pct : p.accuracy_pct;
  const target = p.target_price ? price(p.target_price) : p.direction === 'flat' ? 'stay flat' : 'no target';
  return (
    <Pressable
      onPress={() => (p.run_id ? router.push(`/run/${p.run_id}`) : p.cycle_id ? router.push(`/funds/cycle/${p.cycle_id}`) : null)}
      style={({ pressed }) => ({
        paddingVertical: space.md,
        borderTopWidth: 1,
        borderTopColor: colors.border,
        opacity: pressed ? 0.75 : 1,
      })}
    >
      <Row style={{ justifyContent: 'space-between', gap: space.sm }}>
        <View style={{ flex: 1 }}>
          <Row style={{ gap: 6 }}>
            <Text style={{ color: dirColor, fontWeight: '900' }}>{arrow}</Text>
            <Text style={{ color: colors.text, fontWeight: '700', fontSize: 16 }}>{p.ticker}</Text>
            <Pill
              text={open ? 'open' : p.status === 'scored' ? 'scored' : 'no data'}
              color={open ? colors.accent : p.status === 'scored' ? accuracyColor(p.accuracy_pct) : colors.muted}
            />
            {p.hit_target ? <Pill text="target hit" color={colors.up} /> : null}
          </Row>
          <Body muted style={{ fontSize: 12, marginTop: 2 }}>
            {price(p.entry_price)} → {target} · {p.horizon_text ?? `${p.horizon_hours.toFixed(0)}h`}
            {p.confidence != null ? ` · ${(p.confidence * 100).toFixed(0)}% confident` : ''}
          </Body>
        </View>
        <View style={{ alignItems: 'flex-end' }}>
          {open ? (
            <>
              <Text style={{ color: colors.text, fontWeight: '700' }}>
                {p.current_progress_pct != null ? `${p.current_progress_pct.toFixed(0)}%` : pct(p.current_return_pct)}
              </Text>
              <Text style={{ color: colors.faint, fontSize: 11 }}>{timeLeft(p.time_left_hours)}</Text>
            </>
          ) : (
            <>
              <Text style={{ color: accuracyColor(p.accuracy_pct), fontWeight: '800', fontSize: 16 }}>
                {p.accuracy_pct != null ? `${p.accuracy_pct.toFixed(0)}%` : p.direction_correct ? '✓' : '✗'}
              </Text>
              <Text style={{ color: colors.faint, fontSize: 11 }}>
                got {price(p.price_at_due)} ({pct(p.return_pct, 1)})
              </Text>
            </>
          )}
        </View>
      </Row>
      {(p.target_price || p.direction === 'flat') && (
        <View style={{ marginTop: 8 }}>
          <ProgressBar value={progress} color={open ? colors.accent : undefined} />
        </View>
      )}
      {!open && p.status === 'scored' ? (
        <Body muted style={{ fontSize: 11, marginTop: 4 }}>
          {p.score != null ? `precision ${p.score.toFixed(0)}%` : ''}
          {p.peak_progress_pct != null ? ` · best reach ${p.peak_progress_pct.toFixed(0)}%` : ''}
          {p.hit_stop ? ' · stop-loss hit' : ''}
          {p.note ? ` · ${p.note}` : ''}
        </Body>
      ) : null}
      {p.rationale ? (
        <Body muted numberOfLines={2} style={{ fontSize: 12, marginTop: 4 }}>
          “{p.rationale}”
        </Body>
      ) : null}
    </Pressable>
  );
}

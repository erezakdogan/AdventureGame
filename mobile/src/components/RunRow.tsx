import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { usd, when } from '../lib/format';
import { colors, space } from '../lib/theme';
import type { Run } from '../lib/types';
import { Body, Pill, RatingBadge, Row } from './ui';

export const statusColor: Record<Run['status'], string> = {
  queued: colors.muted,
  running: colors.accent,
  completed: colors.up,
  failed: colors.down,
  cancelled: colors.warn,
};

export function RunRow({ run: r }: { run: Run }) {
  return (
    <Pressable
      onPress={() => router.push(`/run/${r.id}`)}
      style={({ pressed }) => ({
        paddingVertical: space.md,
        borderTopWidth: 1,
        borderTopColor: colors.border,
        opacity: pressed ? 0.7 : 1,
      })}
    >
      <Row style={{ justifyContent: 'space-between', gap: space.sm }}>
        <View style={{ flex: 1 }}>
          <Row style={{ gap: space.sm }}>
            <Text style={{ color: colors.text, fontWeight: '700', fontSize: 16 }}>{r.ticker}</Text>
            <Pill text={r.status} color={statusColor[r.status]} />
            {r.source === 'autopilot' && <Pill text="autopilot" color={colors.info} />}
          </Row>
          <Body muted style={{ fontSize: 12, marginTop: 2 }}>
            as of {r.trade_date} · {when(r.created_at)}
            {r.usage?.cost_usd ? ` · ${usd(r.usage.cost_usd)}` : ''}
          </Body>
        </View>
        {r.rating ? (
          <RatingBadge rating={r.rating} />
        ) : r.status === 'running' || r.status === 'queued' ? (
          <Text style={{ color: colors.accent, fontWeight: '700' }}>{Math.round(r.progress * 100)}%</Text>
        ) : null}
      </Row>
      {(r.status === 'running' || r.status === 'queued') && (
        <View style={{ height: 4, backgroundColor: colors.surfaceAlt, borderRadius: 2, marginTop: 8 }}>
          <View
            style={{
              height: 4,
              width: `${Math.max(4, r.progress * 100)}%`,
              backgroundColor: colors.accent,
              borderRadius: 2,
            }}
          />
        </View>
      )}
    </Pressable>
  );
}

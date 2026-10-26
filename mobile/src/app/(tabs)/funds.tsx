import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { accuracyColor } from '../../components/Forecasts';
import { Body, Button, Card, Empty, ErrorBanner, Label, Pill, Row, Screen } from '../../components/ui';
import { api } from '../../lib/api';
import { money, pct, when, whenFuture } from '../../lib/format';
import { colors, pnlColor, space } from '../../lib/theme';
import type { Fund } from '../../lib/types';
import { useApi } from '../../lib/useApi';

export default function Funds() {
  const list = useApi(() => api.funds(), [], 15000);
  const funds = list.data?.funds ?? [];

  return (
    <Screen refreshing={list.refreshing} onRefresh={list.reload}>
      <Card>
        <Text style={{ color: colors.text, fontSize: 20, fontWeight: '800' }}>Let Claude run a fund 🚀</Text>
        <Body muted style={{ marginTop: 6, fontSize: 14 }}>
          Type an amount of paper money, pick the markets and how often to trade (hourly, day trading, swing or
          long-term), and Claude spreads the money across the stocks it expects to rise. It buys, trims and sells
          on its own, and every forecast it makes is scored against what the price really did.
        </Body>
        <Button title="Create an AI fund" onPress={() => router.push('/funds/new')} style={{ marginTop: space.md }} />
      </Card>

      <ErrorBanner message={list.error} />
      {list.data && funds.length === 0 && <Empty title="No funds yet">Create one above. Each has its own wallet.</Empty>}
      {funds.map((f) => (
        <FundCard key={f.id} f={f} />
      ))}

      <Pressable onPress={() => router.push({ pathname: '/track-record', params: { title: 'All forecasts' } })}>
        <Card>
          <Row style={{ justifyContent: 'space-between' }}>
            <View style={{ flex: 1 }}>
              <Text style={{ color: colors.text, fontWeight: '700', fontSize: 16 }}>Track record 🎯</Text>
              <Body muted style={{ fontSize: 13 }}>How accurate the bots&apos; price forecasts have been</Body>
            </View>
            <Text style={{ color: colors.accent, fontSize: 22 }}>›</Text>
          </Row>
        </Card>
      </Pressable>
    </Screen>
  );
}

function FundCard({ f }: { f: Fund }) {
  const beat = f.benchmark_return_pct != null ? f.total_pnl_pct - f.benchmark_return_pct : null;
  return (
    <Pressable onPress={() => router.push(`/funds/${f.id}`)}>
      <Card>
        <Row style={{ justifyContent: 'space-between' }}>
          <View style={{ flex: 1 }}>
            <Text style={{ color: colors.text, fontWeight: '800', fontSize: 17 }}>{f.name}</Text>
            <Row style={{ gap: 6, marginTop: 4 }}>
              <Pill text={f.style_label} color={colors.info} />
              {f.running ? (
                <Pill text="trading now" color={colors.accent} />
              ) : (
                <Pill text={f.status} color={f.status === 'active' ? colors.up : colors.warn} />
              )}
            </Row>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Text style={{ color: colors.text, fontWeight: '800', fontSize: 18 }}>{money(f.equity)}</Text>
            <Text style={{ color: pnlColor(f.total_pnl), fontWeight: '600' }}>{pct(f.total_pnl_pct)}</Text>
          </View>
        </Row>
        <Row style={{ justifyContent: 'space-between', marginTop: space.md }}>
          <View>
            <Label>vs {f.benchmark_symbol ?? 'market'}</Label>
            <Text style={{ color: pnlColor(beat), fontWeight: '700' }}>
              {beat == null ? '—' : `${beat >= 0 ? '+' : ''}${beat.toFixed(2)} pts`}
            </Text>
          </View>
          <View>
            <Label>Accuracy</Label>
            <Text style={{ color: accuracyColor(f.accuracy.avg_accuracy_pct), fontWeight: '700' }}>
              {f.accuracy.avg_accuracy_pct != null ? `${f.accuracy.avg_accuracy_pct.toFixed(0)}%` : '—'}
              <Text style={{ color: colors.faint, fontWeight: '400' }}> ({f.accuracy.scored ?? 0})</Text>
            </Text>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Label>Next trade check</Label>
            <Text style={{ color: colors.text }}>
              {f.status === 'paused' ? 'paused' : f.next_cycle_at ? whenFuture(f.next_cycle_at) : '—'}
            </Text>
          </View>
        </Row>
        {f.last_error ? (
          <Body style={{ color: colors.down, fontSize: 12, marginTop: 6 }} numberOfLines={2}>
            Last cycle: {f.last_error}
          </Body>
        ) : f.last_cycle_at ? (
          <Body muted style={{ fontSize: 12, marginTop: 6 }}>
            Last cycle {when(f.last_cycle_at)} · {f.cycles} so far
          </Body>
        ) : null}
      </Card>
    </Pressable>
  );
}

import { router, useLocalSearchParams } from 'expo-router';
import { Text, View } from 'react-native';

import { Body, Button, Card, ErrorBanner, Label, Loading, Pill, Row, Screen } from '../../../components/ui';
import { api } from '../../../lib/api';
import { duration, money, pct, price, qty, signedMoney, usd, when } from '../../../lib/format';
import { colors, pnlColor, space } from '../../../lib/theme';
import type { FundDecision } from '../../../lib/types';
import { useApi } from '../../../lib/useApi';

const ACTION_COLOR: Record<FundDecision['action'], string> = {
  buy: colors.up,
  add: colors.up,
  hold: colors.muted,
  trim: colors.warn,
  sell: colors.down,
  avoid: colors.faint,
};

export default function CycleScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const c = useApi(() => api.fundCycle(Number(id)), [id], 5000);
  const cy = c.data;
  if (!cy) return c.error ? <Screen><ErrorBanner message={c.error} /></Screen> : <Loading />;

  const order = { buy: 0, add: 1, sell: 2, trim: 3, hold: 4, avoid: 5 } as const;
  const decisions = [...cy.decisions].sort(
    (a, b) =>
      Number(b.executed === 'filled') - Number(a.executed === 'filled') ||
      order[a.action] - order[b.action] ||
      (b.target_weight_pct ?? 0) - (a.target_weight_pct ?? 0),
  );
  const protective = cy.orders.filter((o) => o.source === 'fund-stop' || o.source === 'fund-target');
  const change = cy.equity_after != null && cy.equity_before != null ? cy.equity_after - cy.equity_before : null;

  return (
    <Screen refreshing={c.refreshing} onRefresh={c.reload}>
      <Card>
        <Row style={{ justifyContent: 'space-between' }}>
          <Text style={{ color: colors.text, fontSize: 18, fontWeight: '800' }}>{when(cy.started_at)}</Text>
          <Pill text={cy.status} color={cy.status === 'failed' ? colors.down : cy.status === 'completed' ? colors.up : colors.accent} />
        </Row>
        <Body muted style={{ fontSize: 12 }}>
          {cy.trigger} check · took {duration(cy.started_at, cy.finished_at)}
          {cy.usage?.cost_usd ? ` · Claude ≈${usd(cy.usage.cost_usd)}` : ''}
          {change != null ? ` · equity ${money(cy.equity_before)} → ${money(cy.equity_after)}` : ''}
        </Body>
        {change != null && Math.abs(change) > 0.005 ? (
          <Text style={{ color: pnlColor(change), fontSize: 12 }}>{signedMoney(change)} (costs and price moves)</Text>
        ) : null}
        {cy.error ? <ErrorBanner message={cy.error} /> : null}
        {cy.market_view ? (
          <>
            <Label style={{ marginTop: space.md, marginBottom: 6 }}>Claude&apos;s market view</Label>
            <Body>{cy.market_view}</Body>
          </>
        ) : null}
      </Card>

      {protective.length > 0 && (
        <Card>
          <Label style={{ marginBottom: space.sm }}>Filled before this check</Label>
          {protective.map((o) => (
            <Body key={o.id} style={{ fontSize: 13 }}>
              {o.source === 'fund-target' ? '🎯 Take-profit' : '🛑 Stop-loss'}: sold {qty(Math.round(o.quantity * 1e4) / 1e4)}{' '}
              {o.symbol} at {price(o.fill_price)}
            </Body>
          ))}
        </Card>
      )}

      {cy.run_ids.length > 0 && (
        <Card>
          <Label style={{ marginBottom: space.sm }}>Agent-team second opinions</Label>
          {cy.run_ids.map((rid) => (
            <Button key={rid} title={`Open analysis #${rid}`} kind="secondary" small onPress={() => router.push(`/run/${rid}`)} />
          ))}
        </Card>
      )}

      <Card>
        <Label style={{ marginBottom: space.sm }}>Decision per ticker</Label>
        {decisions.length === 0 && <Body muted>No decisions in this check.</Body>}
        {decisions.map((d) => (
          <View key={d.ticker} style={{ paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.border }}>
            <Row style={{ justifyContent: 'space-between' }}>
              <Row style={{ gap: 6 }}>
                <Text style={{ color: colors.text, fontWeight: '800', fontSize: 15 }}>{d.ticker}</Text>
                <Pill text={d.action} color={ACTION_COLOR[d.action]} />
                {d.executed === 'filled' ? (
                  <Pill
                    text={`${d.side} ${qty(Math.round((d.quantity ?? 0) * 1e4) / 1e4)} @ ${price(d.fill_price)}`}
                    color={d.side === 'buy' ? colors.up : colors.down}
                  />
                ) : d.executed === 'not held' ? (
                  <Pill text="already out" color={colors.muted} />
                ) : d.executed !== 'no trade' ? (
                  <Pill text={d.executed} color={colors.down} />
                ) : null}
              </Row>
              {d.target_weight_pct != null ? (
                <Text style={{ color: colors.muted, fontSize: 12 }}>target {d.target_weight_pct.toFixed(0)}%</Text>
              ) : null}
            </Row>
            {d.expected_price != null && d.price ? (
              <Body style={{ fontSize: 13, marginTop: 4 }}>
                {price(d.price)} → expects{' '}
                <Text style={{ color: pnlColor(d.expected_move_pct), fontWeight: '700' }}>
                  {price(d.expected_price)} ({pct(d.expected_move_pct, 1)})
                </Text>{' '}
                in {d.horizon_hours != null ? formatHours(d.horizon_hours) : '?'}
                {d.stop_loss ? ` · stop ${price(d.stop_loss)}` : ''}
                {d.confidence != null ? ` · ${(d.confidence * 100).toFixed(0)}% sure` : ''}
              </Body>
            ) : null}
            {d.rationale ? (
              <Body muted style={{ fontSize: 13, marginTop: 2 }}>
                {d.rationale}
              </Body>
            ) : null}
            {d.error ? <Body style={{ color: colors.down, fontSize: 12 }}>{d.error}</Body> : null}
          </View>
        ))}
      </Card>
    </Screen>
  );
}

function formatHours(h: number): string {
  if (h < 48) return `${h.toFixed(h < 10 ? 1 : 0)}h`;
  if (h < 24 * 60) return `${Math.round(h / 24)} days`;
  return `${(h / 730).toFixed(1)} months`;
}

import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { LineChart } from '../../components/LineChart';
import { Body, Card, Empty, ErrorBanner, H1, Label, Loading, Notice, Row, Screen, Segmented } from '../../components/ui';
import { api } from '../../lib/api';
import { money, pct, price, qty, signedMoney } from '../../lib/format';
import { colors, pnlColor, space } from '../../lib/theme';
import type { Account, EquityPoint } from '../../lib/types';
import { useApi } from '../../lib/useApi';

type Range = '7' | '30' | '90' | 'all';

export default function Portfolio() {
  const [range, setRange] = useState<Range>('30');
  const acct = useApi<Account>(() => api.account(), [], 30000);
  const equity = useApi<{ points: EquityPoint[] }>(
    () => api.equity(range === 'all' ? undefined : Number(range)),
    [range],
    60000,
  );

  if (acct.loading && !acct.data) return <Loading />;
  const a = acct.data;
  const points = equity.data?.points ?? [];
  const values = points.map((p) => p.equity);
  if (a && values.length) values.push(a.equity);

  return (
    <Screen
      refreshing={acct.refreshing}
      onRefresh={() => {
        acct.reload();
        equity.reload();
      }}
    >
      <ErrorBanner message={acct.error} />
      {a && (
        <>
          <Card>
            <Label>Paper account value</Label>
            <H1 style={{ marginTop: 4 }}>{money(a.equity)}</H1>
            <Row style={{ gap: space.md, marginTop: 4 }}>
              <Text style={{ color: pnlColor(a.total_pnl), fontWeight: '600' }}>
                {signedMoney(a.total_pnl)} ({pct(a.total_pnl_pct)}) all time
              </Text>
            </Row>
            <Text style={{ color: pnlColor(a.day_pnl), marginTop: 2 }}>{signedMoney(a.day_pnl)} today</Text>
            <View style={{ marginTop: space.lg }}>
              <LineChart
                series={[{ values, color: a.total_pnl >= 0 ? colors.up : colors.down, fill: true }]}
                baseline={a.starting_cash}
                height={150}
              />
            </View>
            <Segmented
              style={{ marginTop: space.md }}
              value={range}
              onChange={setRange}
              options={[
                { label: '1W', value: '7' },
                { label: '1M', value: '30' },
                { label: '3M', value: '90' },
                { label: 'All', value: 'all' },
              ]}
            />
          </Card>

          <Row style={{ gap: space.md }}>
            <Stat label="Cash" value={money(a.cash)} />
            <Stat label="Invested" value={money(a.market_value)} />
          </Row>
          <Row style={{ gap: space.md }}>
            <Stat label="Realized P&L" value={signedMoney(a.realized_pnl)} color={pnlColor(a.realized_pnl)} />
            <Stat label="Fees paid" value={money(a.commissions_paid)} />
          </Row>

          {a.quote_errors.length > 0 && (
            <Notice color={colors.warn}>Some prices could not be refreshed, so their last known value is shown.</Notice>
          )}

          <Card>
            <Label style={{ marginBottom: space.sm }}>Positions</Label>
            {a.positions.length === 0 ? (
              <Empty title="No positions yet">
                Run an AI analysis from the Agents tab, or buy something from Markets.
              </Empty>
            ) : (
              a.positions.map((p) => (
                <Pressable
                  key={p.symbol}
                  onPress={() => router.push(`/symbol/${encodeURIComponent(p.symbol)}`)}
                  style={({ pressed }) => ({
                    paddingVertical: space.md,
                    borderTopWidth: 1,
                    borderTopColor: colors.border,
                    opacity: pressed ? 0.7 : 1,
                  })}
                >
                  <Row style={{ justifyContent: 'space-between' }}>
                    <View style={{ flex: 1 }}>
                      <Text style={{ color: colors.text, fontWeight: '700', fontSize: 16 }}>{p.symbol}</Text>
                      <Body muted style={{ fontSize: 13 }}>
                        {qty(p.quantity)} @ {price(p.avg_price)} · {p.weight_pct.toFixed(1)}%
                      </Body>
                    </View>
                    <View style={{ alignItems: 'flex-end' }}>
                      <Text style={{ color: colors.text, fontWeight: '700', fontSize: 16 }}>{money(p.market_value)}</Text>
                      <Text style={{ color: pnlColor(p.unrealized_pnl), fontSize: 13 }}>
                        {signedMoney(p.unrealized_pnl)} ({pct(p.unrealized_pnl_pct)})
                      </Text>
                    </View>
                  </Row>
                </Pressable>
              ))
            )}
          </Card>
          <Body muted style={{ fontSize: 12, textAlign: 'center' }}>
            Simulated account. Prices from Yahoo Finance; orders fill at the last price plus your slippage setting.
          </Body>
        </>
      )}
    </Screen>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Card style={{ flex: 1, padding: space.md }}>
      <Label>{label}</Label>
      <Text style={{ color: color ?? colors.text, fontSize: 17, fontWeight: '700', marginTop: 4 }}>{value}</Text>
    </Card>
  );
}

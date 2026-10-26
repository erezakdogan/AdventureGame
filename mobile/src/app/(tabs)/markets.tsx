import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Body, Button, Card, Empty, ErrorBanner, Field, Label, Row, Screen } from '../../components/ui';
import { api } from '../../lib/api';
import { pct, price } from '../../lib/format';
import { colors, pnlColor, space } from '../../lib/theme';
import type { Quote } from '../../lib/types';
import { useApi } from '../../lib/useApi';

const IDEAS = ['AAPL', 'NVDA', 'MSFT', 'TSLA', 'SPY', 'BTC-USD', 'ETH-USD', '7203.T', 'AZN.L'];

export default function Markets() {
  const [symbol, setSymbol] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const list = useApi(
    async () => {
      const { symbols } = await api.watchlist();
      if (!symbols.length) return { symbols, quotes: [] as Quote[], errors: {} as Record<string, string> };
      const q = await api.quotes(symbols);
      return { symbols, ...q };
    },
    [],
    30000,
  );

  const add = async (s: string) => {
    if (!s.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.watch(s.trim());
      setSymbol('');
      list.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (s: string) => {
    await api.unwatch(s).catch(() => undefined);
    list.refresh();
  };

  const quotes = new Map((list.data?.quotes ?? []).map((q) => [q.symbol, q]));

  return (
    <Screen refreshing={list.refreshing} onRefresh={list.reload}>
      <Card>
        <Field
          label="Add a ticker"
          value={symbol}
          onChangeText={setSymbol}
          autoCapitalize="characters"
          placeholder="AAPL, BTC-USD, 0700.HK…"
          onSubmitEditing={() => add(symbol)}
          returnKeyType="done"
          hint="Any Yahoo Finance symbol: US stocks and ETFs, crypto (BTC-USD) or other markets with their suffix (.T, .L, .HK, .NS)."
        />
        <Row style={{ gap: space.sm }}>
          <Button title="Add to watchlist" onPress={() => add(symbol)} loading={busy} style={{ flex: 1 }} />
          <Button
            title="Open"
            kind="secondary"
            onPress={() => symbol.trim() && router.push(`/symbol/${encodeURIComponent(symbol.trim().toUpperCase())}`)}
          />
        </Row>
        <ErrorBanner message={error} />
      </Card>

      <ErrorBanner message={list.error} />
      <Card>
        <Label style={{ marginBottom: space.sm }}>Watchlist</Label>
        {list.data && list.data.symbols.length === 0 ? (
          <>
            <Empty title="Your watchlist is empty">Tap an idea to add it:</Empty>
            <Row style={{ flexWrap: 'wrap', gap: space.sm, justifyContent: 'center' }}>
              {IDEAS.map((s) => (
                <Button key={s} title={s} small kind="secondary" onPress={() => add(s)} />
              ))}
            </Row>
          </>
        ) : (
          (list.data?.symbols ?? []).map((s) => {
            const q = quotes.get(s);
            return (
              <Pressable
                key={s}
                onPress={() => router.push(`/symbol/${encodeURIComponent(s)}`)}
                onLongPress={() => remove(s)}
                style={({ pressed }) => ({
                  paddingVertical: space.md,
                  borderTopWidth: 1,
                  borderTopColor: colors.border,
                  opacity: pressed ? 0.7 : 1,
                })}
              >
                <Row style={{ justifyContent: 'space-between' }}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ color: colors.text, fontWeight: '700', fontSize: 16 }}>{s}</Text>
                    <Body muted numberOfLines={1} style={{ fontSize: 13 }}>
                      {q?.name ?? list.data?.errors?.[s] ?? ''}
                    </Body>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={{ color: colors.text, fontWeight: '700', fontSize: 16 }}>{price(q?.price)}</Text>
                    <Text style={{ color: pnlColor(q?.change_pct), fontSize: 13 }}>{pct(q?.change_pct)}</Text>
                  </View>
                </Row>
              </Pressable>
            );
          })
        )}
        {list.data && list.data.symbols.length > 0 && (
          <Body muted style={{ fontSize: 12, marginTop: space.sm }}>Long-press a row to remove it.</Body>
        )}
      </Card>
    </Screen>
  );
}

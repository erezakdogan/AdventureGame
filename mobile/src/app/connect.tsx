import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Body, Button, Card, ErrorBanner, Field, H1, Label } from '../components/ui';
import { api, normalizeUrl } from '../lib/api';
import { useSession } from '../lib/session';
import { colors, space } from '../lib/theme';

export default function Connect() {
  const { connect } = useSession();
  const [url, setUrl] = useState('http://192.168.1.10:8000');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const conn = { url: normalizeUrl(url), token: token.trim() };
    setBusy(true);
    setError(null);
    try {
      await api.health(conn);
      await api.checkConnection(conn);
      await connect(conn);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={{ padding: space.lg, gap: space.lg }} keyboardShouldPersistTaps="handled">
          <View style={{ marginTop: space.xl }}>
            <Text style={{ fontSize: 44 }}>📈</Text>
            <H1 style={{ marginTop: space.sm }}>Paper Trader</H1>
            <Body muted style={{ marginTop: space.sm }}>
              A team of Claude-powered agents (analysts, researchers, a trader and risk managers) researches
              stocks and crypto and trades a simulated account. No real money is involved.
            </Body>
          </View>

          <Card>
            <Label style={{ marginBottom: space.md }}>Connect to your server</Label>
            <Field
              label="Server URL"
              value={url}
              onChangeText={setUrl}
              autoCapitalize="none"
              keyboardType="url"
              hint="Shown when you start the backend (python -m app). Phone and computer must be on the same Wi-Fi."
            />
            <Field
              label="Access token"
              value={token}
              onChangeText={setToken}
              autoCapitalize="none"
              secureTextEntry
              placeholder="printed next to the URL"
            />
            <ErrorBanner message={error} />
            <Button
              title="Connect"
              onPress={submit}
              loading={busy}
              disabled={!url.trim() || !token.trim()}
              style={{ marginTop: space.md }}
            />
          </Card>

          <Body muted style={{ fontSize: 13 }}>
            The server runs TradingAgents and holds your Anthropic API key, so the key never lives on this
            phone. Research and education only, not financial advice.
          </Body>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

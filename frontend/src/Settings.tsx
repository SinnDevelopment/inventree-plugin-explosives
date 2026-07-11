import { useState } from 'react';
import { Alert, Button, Code, Group, List, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';

import type { InvenTreePluginContext } from '@inventreedb/ui';

import { urls } from './api';

interface BootstrapResult {
  created: string[];
  existing: string[];
  errors: string[];
}

/**
 * Plugin settings page.
 *
 * InvenTree gives plugins no activation hook, so if the parameter templates were
 * not created at load time (for instance the plugin first loaded during a
 * migration, before the database was ready) the setup button creates them without
 * requiring a server restart.
 */
function PluginSettingsDisplay({ context }: { context: InvenTreePluginContext }) {
  const [result, setResult] = useState<BootstrapResult | null>(null);
  const [running, setRunning] = useState(false);

  const runSetup = async () => {
    setRunning(true);

    try {
      const response = await context.api.post(urls.bootstrap(), {});
      const data = response.data as BootstrapResult;

      setResult(data);

      notifications.show({
        title: 'Setup complete',
        message: data.created.length
          ? `Created ${data.created.length} parameter template(s).`
          : 'All parameter templates were already present.',
        color: data.errors.length ? 'orange' : 'green'
      });
    } catch (_error) {
      notifications.show({
        title: 'Setup failed',
        message: 'Could not run plugin setup. Are you signed in as an admin?',
        color: 'red'
      });
    } finally {
      setRunning(false);
    }
  };

  return (
    <Stack gap="md">
      <Alert color="blue" title="Parameter templates">
        <Stack gap="xs">
          <Text size="sm">
            This plugin stores explosive properties as InvenTree parameters. It
            creates the templates it needs automatically, but you can re-run setup
            here if any are missing.
          </Text>
          <Text size="sm">
            Explosive properties live on the <b>Part</b>. The licensed limit lives
            on the <b>Stock Location</b>, as{' '}
            <Code>Maximum Net Explosive Quantity</Code>.
          </Text>
        </Stack>
      </Alert>

      <Group>
        <Button onClick={runSetup} loading={running}>
          Run setup
        </Button>
      </Group>

      {result?.created.length ? (
        <Alert color="green" title="Created">
          <List size="sm">
            {result.created.map((name) => (
              <List.Item key={name}>{name}</List.Item>
            ))}
          </List>
        </Alert>
      ) : null}

      {result?.errors.length ? (
        <Alert color="red" title="Configuration problems">
          <List size="sm">
            {result.errors.map((error) => (
              <List.Item key={error}>{error}</List.Item>
            ))}
          </List>
        </Alert>
      ) : null}
    </Stack>
  );
}

export function RenderPluginSettings(context: InvenTreePluginContext) {
  return <PluginSettingsDisplay context={context} />;
}

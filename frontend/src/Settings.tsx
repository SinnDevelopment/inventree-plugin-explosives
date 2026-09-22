import type { InvenTreePluginContext } from '@inventreedb/ui';
import { Alert, Button, Code, Group, List, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { type BootstrapStatus, fetchJson, urls } from './api';

interface BootstrapResult {
  created: string[];
  existing: string[];
  errors: string[];
}

/**
 * Plugin settings page.
 *
 * The parameter templates this plugin needs are created automatically when it is
 * enabled, re-checked daily, and can be repaired here. This page loads the
 * current status on mount and shows a red banner if any template is missing or
 * misconfigured — so a failed bootstrap is visible here rather than only in the
 * server log.
 */
function PluginSettingsDisplay({
  context
}: {
  context: InvenTreePluginContext;
}) {
  const [result, setResult] = useState<BootstrapResult | null>(null);
  const [running, setRunning] = useState(false);

  const status = useQuery(
    {
      queryKey: ['explosives-status'],
      queryFn: () => fetchJson<BootstrapStatus>(context, urls.bootstrapStatus())
    },
    context.queryClient
  );

  const runSetup = async () => {
    setRunning(true);

    try {
      const response = await context.api.post(urls.bootstrap(), {});
      const data = response.data as BootstrapResult;

      setResult(data);

      // Refetch the status so the banner reflects the repair without a reload.
      status.refetch();

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

  const notReady = status.data && !status.data.ready;

  return (
    <Stack gap='md'>
      {notReady ? (
        <Alert color='red' title='Setup incomplete'>
          <Stack gap='xs'>
            <Text size='sm'>
              One or more parameter templates are missing or misconfigured.
              Explosive fields and magazine totals will not work until this is
              fixed. Press <b>Run setup</b> below.
            </Text>
            {status.data?.errors.length ? (
              <List size='sm'>
                {status.data.errors.map((error) => (
                  <List.Item key={error}>{error}</List.Item>
                ))}
              </List>
            ) : null}
          </Stack>
        </Alert>
      ) : null}

      <Alert color='blue' title='Parameter templates'>
        <Stack gap='xs'>
          <Text size='sm'>
            This plugin stores explosive properties as InvenTree parameters. It
            creates the templates it needs automatically, but you can re-run
            setup here if any are missing.
          </Text>
          <Text size='sm'>
            Explosive properties live on the <b>Part</b>. The licensed limit
            lives on the <b>Stock Location</b>, as{' '}
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
        <Alert color='green' title='Created'>
          <List size='sm'>
            {result.created.map((name) => (
              <List.Item key={name}>{name}</List.Item>
            ))}
          </List>
        </Alert>
      ) : null}

      {result?.errors.length ? (
        <Alert color='red' title='Configuration problems'>
          <List size='sm'>
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

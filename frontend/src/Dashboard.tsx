import {
  checkPluginVersion,
  type InvenTreePluginContext
} from '@inventreedb/ui';
import {
  Alert,
  Badge,
  Group,
  Loader,
  Progress,
  Stack,
  Text,
  Title
} from '@mantine/core';
import { useQuery } from '@tanstack/react-query';

import { fetchJson, kg, type LocationNEQ, urls, utilisationColor } from './api';

/** Licensed magazines, breached first, then by utilisation. */
function MagazineDashboard({ context }: { context: InvenTreePluginContext }) {
  const query = useQuery(
    {
      queryKey: ['explosives-magazines'],
      queryFn: () => fetchJson<LocationNEQ[]>(context, urls.locationSummary())
    },
    context.queryClient
  );

  if (query.isLoading) {
    return (
      <Group>
        <Loader size='sm' />
        <Text>Loading magazines…</Text>
      </Group>
    );
  }

  const magazines = query.data;

  if (query.isError || !magazines) {
    return (
      <Alert color='red' title='Unavailable'>
        Could not load magazine data.
      </Alert>
    );
  }

  if (magazines.length === 0) {
    return (
      <Alert color='blue' title='No licensed magazines'>
        Set the “Maximum Net Explosive Quantity” parameter on a stock location
        to track it here.
      </Alert>
    );
  }

  const breached = magazines.filter((magazine) => magazine.over_limit);

  return (
    <Stack gap='sm'>
      <Group justify='space-between'>
        <Title order={5}>Magazine NEQ</Title>
        {breached.length > 0 ? (
          <Badge color='red'>{breached.length} over limit</Badge>
        ) : (
          <Badge color='green'>All within limits</Badge>
        )}
      </Group>

      {magazines.map((magazine) => {
        const color = utilisationColor(
          magazine.utilisation,
          magazine.over_limit
        );
        const percent = magazine.over_limit
          ? 100
          : Math.min(100, (magazine.utilisation ?? 0) * 100);

        return (
          <Stack key={magazine.location_id} gap={4}>
            <Group justify='space-between' wrap='nowrap'>
              <Text
                size='sm'
                fw={500}
                truncate
                style={{ cursor: 'pointer' }}
                onClick={() =>
                  context.navigate(`/stock/location/${magazine.location_id}/`)
                }
              >
                {magazine.location_name}
              </Text>
              <Text size='xs' c='dimmed' style={{ whiteSpace: 'nowrap' }}>
                {kg(magazine.neq_kg, 1)} / {kg(magazine.limit_kg, 1)}
              </Text>
            </Group>
            <Progress value={percent} color={color} size='sm' />
          </Stack>
        );
      })}
    </Stack>
  );
}

export function RenderMagazineDashboard(context: InvenTreePluginContext) {
  checkPluginVersion(context);

  return <MagazineDashboard context={context} />;
}

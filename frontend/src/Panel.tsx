import {
  Alert,
  Badge,
  Card,
  Group,
  List,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title
} from '@mantine/core';
import { useQuery } from '@tanstack/react-query';

import { checkPluginVersion, type InvenTreePluginContext } from '@inventreedb/ui';

import { type PartExplosive, fetchJson, kg, urls } from './api';

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text fw={600}>{value}</Text>
    </Stack>
  );
}

/**
 * Explosive properties of a Part.
 *
 * Only rendered for parts flagged as explosive — the backend omits this panel
 * entirely for everything else.
 */
function PartPanel({ context }: { context: InvenTreePluginContext }) {
  const partId = context.id;

  const query = useQuery(
    {
      queryKey: ['explosives-part', partId],
      queryFn: () => fetchJson<PartExplosive>(context, urls.part(partId!)),
      enabled: !!partId
    },
    context.queryClient
  );

  if (query.isLoading) {
    return (
      <Group>
        <Loader size="sm" />
        <Text>Loading explosive data…</Text>
      </Group>
    );
  }

  const data = query.data;

  if (query.isError || !data) {
    return (
      <Alert color="red" title="Could not load explosives data">
        The plugin API did not respond. Check that the <b>Enable plugin URLs</b>{' '}
        (ENABLE_PLUGINS_URL) global setting is switched on.
      </Alert>
    );
  }

  return (
    <Stack gap="md">
      {data.issues.length > 0 ? (
        <Alert color="orange" title="Data integrity issues">
          <List size="sm">
            {data.issues.map((issue) => (
              <List.Item key={issue}>{issue}</List.Item>
            ))}
          </List>
        </Alert>
      ) : null}

      <Card withBorder padding="md">
        <Title order={5} mb="md">
          Classification
        </Title>

        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <Field
            label="Classification code"
            value={
              data.classification_code ? (
                <Badge size="lg" variant="filled">
                  {data.classification_code}
                </Badge>
              ) : (
                '—'
              )
            }
          />
          <Field label="Hazard division" value={data.division ?? '—'} />
          <Field
            label="Compatibility group"
            value={data.compatibility_group ?? '—'}
          />
          <Field label="UN number" value={data.un_number ?? '—'} />
        </SimpleGrid>

        <Stack gap={2} mt="md">
          <Text size="sm" c="dimmed">
            Proper shipping name
          </Text>
          <Text fw={600}>{data.proper_shipping_name ?? '—'}</Text>
        </Stack>
      </Card>

      <Card withBorder padding="md">
        <Title order={5} mb="md">
          Mass (per unit)
        </Title>

        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <Field
            label="Net explosive quantity"
            value={kg(data.neq_per_unit_kg)}
          />
          <Field label="Gross mass" value={kg(data.gross_mass_per_unit_kg)} />
          <Field
            label="Packaging / inert mass"
            value={
              data.gross_mass_per_unit_kg !== null &&
              data.neq_per_unit_kg !== null
                ? kg(data.gross_mass_per_unit_kg - data.neq_per_unit_kg)
                : '—'
            }
          />
        </SimpleGrid>

        <Text size="xs" c="dimmed" mt="sm">
          Magazine totals are computed as stock quantity × net explosive quantity
          per unit.
        </Text>
      </Card>
    </Stack>
  );
}

export function RenderPartPanel(context: InvenTreePluginContext) {
  checkPluginVersion(context);

  return <PartPanel context={context} />;
}

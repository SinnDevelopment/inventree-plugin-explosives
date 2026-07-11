import {
  checkPluginVersion,
  type InvenTreePluginContext
} from '@inventreedb/ui';
import {
  Alert,
  Badge,
  Card,
  Group,
  Loader,
  RingProgress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title
} from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { fetchJson, kg, type LocationNEQ, urls, utilisationColor } from './api';

/**
 * NEQ panel for a StockLocation.
 *
 * Rendered on every location, not just licensed ones — otherwise there would be
 * no place to discover that a limit can be set at all.
 */
function LocationPanel({ context }: { context: InvenTreePluginContext }) {
  const locationId = context.id;

  const query = useQuery(
    {
      queryKey: ['explosives-location-neq', locationId],
      queryFn: () =>
        fetchJson<LocationNEQ>(context, urls.locationNEQ(locationId!)),
      enabled: !!locationId
    },
    context.queryClient
  );

  const data = query.data;

  const percent = useMemo(() => {
    if (!data?.limit_kg) {
      return 0;
    }
    return Math.min(100, (data.neq_kg / data.limit_kg) * 100);
  }, [data]);

  if (query.isLoading) {
    return (
      <Group>
        <Loader size='sm' />
        <Text>Calculating net explosive quantity…</Text>
      </Group>
    );
  }

  if (query.isError || !data) {
    return (
      <Alert color='red' title='Could not load explosives data'>
        <Stack gap='xs'>
          <Text>The plugin API did not respond.</Text>
          <Text size='sm' c='dimmed'>
            Check that the <b>Enable plugin URLs</b> (ENABLE_PLUGINS_URL) global
            setting is switched on.
          </Text>
        </Stack>
      </Alert>
    );
  }

  const color = utilisationColor(data.utilisation, data.over_limit);

  return (
    <Stack gap='md'>
      {data.config_errors?.length ? (
        <Alert color='orange' title='Plugin configuration problem'>
          <Stack gap='xs'>
            {data.config_errors.map((error) => (
              <Text key={error} size='sm'>
                {error}
              </Text>
            ))}
          </Stack>
        </Alert>
      ) : null}

      {data.over_limit && data.limit_kg ? (
        <Alert color='red' title='Licensed net explosive quantity exceeded'>
          This location holds <b>{kg(data.neq_kg)}</b> against a licensed limit
          of <b>{kg(data.limit_kg)}</b> — an excess of{' '}
          <b>{kg(data.neq_kg - data.limit_kg)}</b>.
        </Alert>
      ) : null}

      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <Card withBorder padding='md'>
          <Group>
            <RingProgress
              size={140}
              thickness={14}
              sections={[{ value: percent, color }]}
              label={
                <Stack gap={0} align='center'>
                  <Text fw={700} size='lg'>
                    {data.neq_kg.toFixed(2)}
                  </Text>
                  <Text size='xs' c='dimmed'>
                    kg NEQ
                  </Text>
                </Stack>
              }
            />
            <Stack gap={4}>
              <Text size='sm' c='dimmed'>
                Licensed limit
              </Text>
              <Text fw={600}>
                {data.limit_kg ? kg(data.limit_kg) : 'Not licensed'}
              </Text>

              {data.limit_kg ? (
                <>
                  <Text size='sm' c='dimmed' mt='xs'>
                    Utilisation
                  </Text>
                  <Badge color={color} variant='light'>
                    {((data.utilisation ?? 0) * 100).toFixed(1)}%
                  </Badge>
                </>
              ) : (
                <Text size='xs' c='dimmed' maw={220}>
                  Set the “{'Maximum Net Explosive Quantity'}” parameter on this
                  location to track it against a licence.
                </Text>
              )}

              <Text size='sm' c='dimmed' mt='xs'>
                Gross mass
              </Text>
              <Text>{kg(data.gross_mass_kg)}</Text>
            </Stack>
          </Group>

          {data.include_sublocations ? (
            <Text size='xs' c='dimmed' mt='sm'>
              Includes stock held in sublocations.
            </Text>
          ) : null}
        </Card>

        <Card withBorder padding='md'>
          <Title order={5} mb='sm'>
            By hazard division
          </Title>

          {Object.keys(data.by_division).length === 0 ? (
            <Text c='dimmed' size='sm'>
              No explosive stock in this location.
            </Text>
          ) : (
            <Table>
              <Table.Tbody>
                {Object.entries(data.by_division).map(([division, mass]) => (
                  <Table.Tr key={division}>
                    <Table.Td>
                      <Badge variant='light'>{division}</Badge>
                    </Table.Td>
                    <Table.Td ta='right'>{kg(mass)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Card>
      </SimpleGrid>

      <Card withBorder padding='md'>
        <Title order={5} mb='sm'>
          Contributing stock
        </Title>

        {data.items.length === 0 ? (
          <Text c='dimmed' size='sm'>
            No explosive stock in this location.
          </Text>
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Part</Table.Th>
                <Table.Th>Class</Table.Th>
                <Table.Th>UN</Table.Th>
                <Table.Th ta='right'>Qty</Table.Th>
                <Table.Th ta='right'>NEQ / unit</Table.Th>
                <Table.Th ta='right'>NEQ total</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.items.map((item) => (
                <Table.Tr key={item.stock_item_id}>
                  <Table.Td>{item.part_name}</Table.Td>
                  <Table.Td>
                    {item.classification_code ? (
                      <Badge variant='light'>{item.classification_code}</Badge>
                    ) : (
                      <Text c='dimmed' size='sm'>
                        —
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>{item.un_number ?? '—'}</Table.Td>
                  <Table.Td ta='right'>{item.quantity}</Table.Td>
                  <Table.Td ta='right'>{kg(item.neq_per_unit_kg)}</Table.Td>
                  <Table.Td ta='right'>
                    <Text fw={600}>{kg(item.neq_total_kg)}</Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
            <Table.Tfoot>
              <Table.Tr>
                <Table.Th colSpan={5} ta='right'>
                  Total
                </Table.Th>
                <Table.Th ta='right'>{kg(data.neq_kg)}</Table.Th>
              </Table.Tr>
            </Table.Tfoot>
          </Table>
        )}
      </Card>
    </Stack>
  );
}

export function RenderLocationPanel(context: InvenTreePluginContext) {
  checkPluginVersion(context);

  return <LocationPanel context={context} />;
}

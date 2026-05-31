import { source } from '@/lib/source';
import defaultComponents from 'fumadocs-ui/mdx';
import { DocsPage, DocsBody, DocsTitle, DocsDescription } from 'fumadocs-ui/layouts/docs/page';
import { notFound } from 'next/navigation';
import type { MDXContent } from 'mdx/types';
import type { TOCItemType } from 'fumadocs-core/toc';

interface DocPageData {
  title?: string;
  description?: string;
  body: MDXContent;
  toc: TOCItemType[];
}

export default async function Page(props: { params: Promise<{ slug?: string[] }> }) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();
  const { body: MDX, toc, title, description } = page.data as unknown as DocPageData;
  return (
    <DocsPage toc={toc}>
      <DocsTitle>{title}</DocsTitle>
      <DocsDescription>{description}</DocsDescription>
      <DocsBody>
        <MDX components={{ ...defaultComponents }} />
      </DocsBody>
    </DocsPage>
  );
}

export function generateStaticParams() {
  return source.generateParams();
}

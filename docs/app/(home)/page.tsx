import Link from 'next/link';

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="text-4xl font-bold mb-4">YDK -- Yoav Development Kit</h1>
      <p className="text-lg text-gray-600 mb-8">AI-assisted development methodology and CLI toolkit</p>
      <Link href="/docs" className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
        Read the Docs
      </Link>
    </main>
  );
}

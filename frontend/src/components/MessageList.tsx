import React, { useEffect, useRef } from 'react';
import type { Message, Fonte } from '../types';
import { MessageItem } from './MessageItem';
import { EmptyState } from './EmptyState';

interface MessageListProps {
  messages: Message[];
  onSelectPrompt: (prompt: string) => void;
  onSelectSource: (source: Fonte) => void;
  loading: boolean;
  conversazione: string | null;
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  onSelectPrompt,
  onSelectSource,
  loading,
  conversazione,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);
  const vuoto = messages.length === 0;

  useEffect(() => {
    if (vuoto) return;
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, loading, vuoto]);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 md:px-6">
      <div className="mx-auto max-w-3xl pb-44 pt-4">
        {vuoto ? (
          <EmptyState onSelectPrompt={onSelectPrompt} />
        ) : (
          <div className="space-y-3">
            {messages.map((msg, index) => (
              <MessageItem
                key={index}
                message={msg}
                indice={index}
                domandaPrecedente={messages[index - 1]?.content ?? ''}
                conversazione={conversazione}
                onSelectSource={onSelectSource}
              />
            ))}
          </div>
        )}
        <div ref={bottomRef} className="h-px" />
      </div>
    </div>
  );
};

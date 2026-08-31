import React, { useEffect, useRef } from 'react';
import { Message, Fonte } from '../types';
import { MessageItem } from './MessageItem';
import { EmptyState } from './EmptyState';

interface MessageListProps {
  messages: Message[];
  onSelectPrompt: (prompt: string) => void;
  onSelectSource: (source: Fonte) => void;
  loading: boolean;
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  onSelectPrompt,
  onSelectSource,
  loading,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  return (
    <div className="flex-1 overflow-y-auto px-4 md:px-6 py-6 space-y-6">
      {/* Centered reading canvas matching Claude & ChatGPT */}
      <div className="max-w-2xl mx-auto space-y-6 pb-32">
        {messages.length === 0 ? (
          <EmptyState onSelectPrompt={onSelectPrompt} />
        ) : (
          messages.map((msg, index) => (
            <MessageItem
              key={index}
              message={msg}
              index={index}
              onSelectSource={onSelectSource}
            />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};

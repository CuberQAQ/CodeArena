import { useState } from 'react'
import { Button } from '@/components/ui/button'

function App() {
  const [count, setCount] = useState(0)

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center text-foreground">
      <h1 className="text-4xl font-bold mb-4">Code Arena</h1>
      <p className="text-muted-foreground mb-8">
        Competitive Programming Gamification Platform
      </p>
      <Button onClick={() => setCount((c) => c + 1)}>
        Count is {count}
      </Button>
    </div>
  )
}

export default App

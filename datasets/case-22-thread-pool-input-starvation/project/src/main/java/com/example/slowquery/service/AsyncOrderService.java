package com.example.slowquery.service;

import com.example.slowquery.dto.OrderVO;
import com.example.slowquery.mapper.OrderMapper;
import com.example.slowquery.model.Order;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

@Service
public class AsyncOrderService {

    private final OrderMapper orderMapper;

    /**
     * 共享调度器：交互式快照查询与阻塞式分析任务都提交到这一个有限线程池。
     */
    private final ThreadPoolExecutor dispatcher =
            new ThreadPoolExecutor(
                    4,
                    4,
                    60L,
                    TimeUnit.SECONDS,
                    new LinkedBlockingQueue<>(1000),
                    new NamedThreadFactory("order-dispatch-"),
                    new ThreadPoolExecutor.AbortPolicy());

    public AsyncOrderService(OrderMapper orderMapper) {
        this.orderMapper = orderMapper;
    }

    /**
     * 交互式快照：短查询任务，提交到共享调度器后同步取回结果。
     */
    public List<OrderVO> asyncRecent(long userId, int size) {
        try {
            return dispatcher.submit(() -> {
                List<Order> orders = orderMapper.findOrdersByUser(userId, size);
                List<OrderVO> result = new ArrayList<>();
                for (Order order : orders) {
                    OrderVO vo = new OrderVO();
                    vo.setOrderId(order.getId());
                    vo.setOrderNo(order.getOrderNo());
                    vo.setAmount(order.getAmount());
                    vo.setStatus(order.getStatus());
                    vo.setCreatedAt(order.getCreatedAt());
                    result.add(vo);
                }
                return result;
            }).get();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(e);
        } catch (ExecutionException e) {
            Throwable cause = e.getCause();
            if (cause instanceof RuntimeException runtimeException) {
                throw runtimeException;
            }
            throw new IllegalStateException(cause);
        }
    }

    /**
     * 分析报表：把 rounds 个阻塞式推理任务提交到同一个共享调度器，并等待全部完成。
     */
    public List<String> analyze(long userId, int rounds) {
        List<Future<String>> futures = new ArrayList<>();
        for (int i = 0; i < rounds; i++) {
            final int round = i;
            futures.add(dispatcher.submit(() -> {
                List<Order> orders = orderMapper.findOrdersByUser(userId, 50);
                sleepQuietly(500);
                return "round-" + round + ":" + orders.size();
            }));
        }

        List<String> results = new ArrayList<>();
        for (Future<String> future : futures) {
            try {
                results.add(future.get());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(e);
            } catch (ExecutionException e) {
                throw new IllegalStateException(e.getCause());
            }
        }
        return results;
    }

    private static void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static final class NamedThreadFactory implements ThreadFactory {
        private final String prefix;
        private final AtomicInteger counter = new AtomicInteger(1);

        private NamedThreadFactory(String prefix) {
            this.prefix = prefix;
        }

        @Override
        public Thread newThread(Runnable runnable) {
            Thread thread = new Thread(runnable);
            thread.setName(prefix + counter.getAndIncrement());
            thread.setDaemon(false);
            return thread;
        }
    }
}

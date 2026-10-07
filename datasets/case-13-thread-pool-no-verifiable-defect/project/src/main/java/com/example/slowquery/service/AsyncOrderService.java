package com.example.slowquery.service;

import com.example.slowquery.dto.OrderVO;
import com.example.slowquery.mapper.OrderMapper;
import com.example.slowquery.model.Order;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

@Service
public class AsyncOrderService {

    private final OrderMapper orderMapper;

    private final ThreadPoolExecutor executor =
            new ThreadPoolExecutor(
                    16,
                    16,
                    60L,
                    TimeUnit.SECONDS,
                    new LinkedBlockingQueue<>(1000),
                    new NamedThreadFactory("order-async-"),
                    new ThreadPoolExecutor.AbortPolicy());

    public AsyncOrderService(OrderMapper orderMapper) {
        this.orderMapper = orderMapper;
    }

    public List<OrderVO> asyncRecent(long userId, int size) {
        try {
            return executor.submit(() -> {
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

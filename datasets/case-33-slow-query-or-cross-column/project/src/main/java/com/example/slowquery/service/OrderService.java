package com.example.slowquery.service;

import com.example.slowquery.mapper.OrderMapper;
import com.example.slowquery.model.Order;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class OrderService {

    private final OrderMapper orderMapper;

    public OrderService(OrderMapper orderMapper) {
        this.orderMapper = orderMapper;
    }

    public List<Order> search(long userId, String status, int limit) {
        return orderMapper.findOrdersByUserOrStatus(userId, status, limit);
    }
}

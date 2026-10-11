package com.example.slowquery.service;

import com.example.slowquery.config.SummaryLimitResolver;
import com.example.slowquery.dto.OrderVO;
import com.example.slowquery.mapper.OrderMapper;
import com.example.slowquery.model.Order;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class OrderService {

    private final OrderMapper orderMapper;
    private final SummaryLimitResolver summaryLimitResolver;

    public OrderService(OrderMapper orderMapper, SummaryLimitResolver summaryLimitResolver) {
        this.orderMapper = orderMapper;
        this.summaryLimitResolver = summaryLimitResolver;
    }

    public List<OrderVO> recentByUser(Long userId, int size) {
        List<Order> orders = orderMapper.findOrdersByUser(userId, size);
        return toVoList(orders);
    }

    public List<OrderVO> summary() {
        int limit = summaryLimitResolver.resolve();
        List<Order> orders = orderMapper.findRecent(limit);
        return toVoList(orders);
    }

    private List<OrderVO> toVoList(List<Order> orders) {
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
    }
}

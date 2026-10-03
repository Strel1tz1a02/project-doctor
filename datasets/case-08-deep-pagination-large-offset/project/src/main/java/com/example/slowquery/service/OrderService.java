package com.example.slowquery.service;

import com.example.slowquery.dto.OrderVO;
import com.example.slowquery.dto.PageVO;
import com.example.slowquery.mapper.OrderMapper;
import com.example.slowquery.model.Order;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class OrderService {

    private final OrderMapper orderMapper;

    public OrderService(OrderMapper orderMapper) {
        this.orderMapper = orderMapper;
    }

    public PageVO pageOrders(int page, int size) {
        int offset = (page - 1) * size;
        List<Order> orders = orderMapper.findOrdersByPage(offset, size);
        long total = orderMapper.countOrders();

        List<OrderVO> items = new ArrayList<>();
        for (Order order : orders) {
            OrderVO vo = new OrderVO();
            vo.setOrderId(order.getId());
            vo.setOrderNo(order.getOrderNo());
            vo.setAmount(order.getAmount());
            vo.setStatus(order.getStatus());
            vo.setCreatedAt(order.getCreatedAt());
            items.add(vo);
        }

        PageVO result = new PageVO();
        result.setPage(page);
        result.setSize(size);
        result.setTotal(total);
        result.setItems(items);
        return result;
    }
}

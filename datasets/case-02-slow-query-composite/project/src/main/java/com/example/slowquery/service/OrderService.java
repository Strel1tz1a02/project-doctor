package com.example.slowquery.service;

import com.example.slowquery.dto.OrderVO;
import com.example.slowquery.mapper.OrderMapper;
import com.example.slowquery.model.Order;
import com.example.slowquery.model.User;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class OrderService {

    private final OrderMapper orderMapper;

    public OrderService(OrderMapper orderMapper) {
        this.orderMapper = orderMapper;
    }

    public List<OrderVO> searchSlow(String email, String status, int page, int size) {
        int offset = (page - 1) * size;

        List<Order> orders = orderMapper.findSlowOrders(email, status, offset, size);
        List<OrderVO> result = new ArrayList<>();

        for (Order order : orders) {
            // N+1：每条订单都查一次用户
            User user = orderMapper.findUserById(order.getUserId());

            OrderVO vo = new OrderVO();
            vo.setOrderId(order.getId());
            vo.setOrderNo(order.getOrderNo());
            vo.setAmount(order.getAmount());
            vo.setStatus(order.getStatus());
            vo.setCreatedAt(order.getCreatedAt());
            vo.setUserEmail(user.getEmail());
            vo.setUserName(user.getName());
            result.add(vo);
        }

        return result;
    }

    public long countSlow(String email, String status) {
        return orderMapper.countSlowOrders(email, status);
    }
}

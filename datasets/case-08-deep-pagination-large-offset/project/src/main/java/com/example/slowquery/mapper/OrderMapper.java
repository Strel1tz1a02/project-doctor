package com.example.slowquery.mapper;

import com.example.slowquery.model.Order;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface OrderMapper {

    @Select(
        "SELECT * FROM orders " +
        "ORDER BY created_at DESC " +
        "LIMIT #{offset}, #{size}"
    )
    List<Order> findOrdersByPage(@Param("offset") int offset, @Param("size") int size);

    @Select("SELECT COUNT(*) FROM orders")
    long countOrders();
}

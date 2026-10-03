package com.example.slowquery.mapper;

import com.example.slowquery.model.Order;
import com.example.slowquery.model.User;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface OrderMapper {

    @Select(
        "SELECT * FROM orders " +
        "ORDER BY created_at DESC " +
        "LIMIT #{size}"
    )
    List<Order> findRecentOrders(@Param("size") int size);

    @Select(
        "SELECT id, email, name, created_at FROM users " +
        "WHERE id = #{id}"
    )
    User findUserById(@Param("id") Long id);
}

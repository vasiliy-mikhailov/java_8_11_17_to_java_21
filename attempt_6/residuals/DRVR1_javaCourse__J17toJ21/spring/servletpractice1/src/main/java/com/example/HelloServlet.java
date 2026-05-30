package com.example;

import jakarta.servlet.http.HttpServlet;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

public class HelloServlet extends HttpServlet {

    @Override
    public void service(HttpServletRequest req, HttpServletResponse response) {
        System.out.println("in service");
        try {
            response.getWriter().println("hello world");

        } catch (Exception e) {
            // TODO: handle exception
        }
    }
}
